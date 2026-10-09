#requires -Version 5.1
<#
.SYNOPSIS
Read the active SOLIDWORKS assembly and export Cabinet Flow CSV plus an audit JSON.
.DESCRIPTION
Windows PowerShell 5.1, 64-bit, with SOLIDWORKS 2018 or newer is required.
Reads only: no document opening, resolving, configuration switching, rebuild, or save.
The CSV is an occurrence-based parts list, not SOLIDWORKS drawing BOM/cut-list output.
Before running, manually fully resolve, rebuild, inspect, and save the assembly.
.EXAMPLE
powershell.exe -NoProfile -STA -File .\Export-SolidWorksBOM.ps1 -OutputCsv C:\CabinetFlow\order-001.csv -AssemblyQuantity 3
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputCsv,
    [ValidateRange(1, 1000000)][int]$AssemblyQuantity = 1,
    [string]$InteropPath,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop') {
    throw 'Use 64-bit Windows PowerShell 5.1 (powershell.exe), not PowerShell 7/macOS.'
}
if (-not [Environment]::Is64BitProcess) { throw 'Use the 64-bit Windows PowerShell host.' }
if ([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
    throw 'Start powershell.exe with -STA.'
}
$OutputCsv = [IO.Path]::GetFullPath($OutputCsv)
if ([IO.Path]::GetExtension($OutputCsv) -ne '.csv') { throw 'OutputCsv must end in .csv.' }
$auditPath = $OutputCsv + '.audit.json'
foreach ($path in @($OutputCsv, $auditPath)) {
    if ((Test-Path -LiteralPath $path) -and -not $Force) { throw "Output exists: $path. Choose a new path or use -Force." }
}
if (-not $InteropPath) {
    $roots = @(
        (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS\api\redist'),
        (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS')
    )
    foreach ($root in $roots) {
        $candidate = Join-Path $root 'SolidWorks.Interop.sldworks.dll'
        if (Test-Path -LiteralPath $candidate) { $InteropPath = $candidate; break }
    }
}
if (-not $InteropPath -or -not (Test-Path -LiteralPath $InteropPath -PathType Leaf)) {
    throw 'SOLIDWORKS interop DLL not found. Supply -InteropPath with the installed SOLIDWORKS api\redist\SolidWorks.Interop.sldworks.dll path.'
}
$InteropPath = (Resolve-Path -LiteralPath $InteropPath).Path
[void][Reflection.Assembly]::LoadFrom($InteropPath)

$bridgeSource = @'
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;

namespace CabinetFlowBridge {
    public sealed class PartRow {
        public string id, part_number, name, material, category;
        public string length_mm, width_mm, thickness_mm, unit = "mm", finish;
        public int quantity;
        public string source_file, source_reference, revision;
    }
    public sealed class ExportResult {
        public string assembly_file, configuration;
        public List<PartRow> rows = new List<PartRow>();
        public List<string> warnings = new List<string>();
        public int suppressed_instances;
    }
    public static class Reader {
        private sealed class ReadValue { public bool found; public string value = ""; }

        public static ExportResult Read(object application, int assemblyQuantity) {
            ISldWorks app = (ISldWorks)application;
            IModelDoc2 model = app.ActiveDoc as IModelDoc2;
            if (model == null || model.GetType() != 2) {
                throw new InvalidOperationException("Open and activate a SOLIDWORKS assembly before exporting.");
            }
            string assemblyPath = model.GetPathName();
            if (String.IsNullOrWhiteSpace(assemblyPath)) {
                throw new InvalidOperationException("Save the active assembly first so that source evidence has a stable path.");
            }
            ExportResult result = new ExportResult();
            result.assembly_file = assemblyPath;
            result.configuration = model.ConfigurationManager.ActiveConfiguration.Name;
            result.warnings.Add("Quantity is non-suppressed component occurrence count multiplied by AssemblyQuantity. Drawing BOM exclusions, promoted/hidden BOM children, weldment cut lists and custom BOM quantity rules are not applied.");
            result.warnings.Add("Properties are read from the current in-memory assembly using cached reads only. Manually resolve, rebuild and save all relevant configurations before export; review against the released engineering BOM.");
            Dictionary<string, PartRow> groups = new Dictionary<string, PartRow>(StringComparer.OrdinalIgnoreCase);
            Array roots = ((IAssemblyDoc)model).GetComponents(true) as Array;
            if (roots != null) {
                foreach (object item in roots) Walk((IComponent2)item, assemblyQuantity, result, groups, 0);
            }
            result.rows.AddRange(groups.Values);
            result.rows.Sort(delegate(PartRow a, PartRow b) { return StringComparer.OrdinalIgnoreCase.Compare(a.id, b.id); });
            if (result.rows.Count == 0) throw new InvalidOperationException("No resolved, non-suppressed leaf components were found; no CSV written.");
            return result;
        }

        private static void Walk(IComponent2 component, int multiplier, ExportResult result, Dictionary<string, PartRow> groups, int depth) {
            if (depth > 100) throw new InvalidOperationException("Assembly nesting exceeds 100 levels; inspect the assembly.");
            if (component.IsSuppressed()) { result.suppressed_instances++; return; }
            string occurrence = component.Name2;
            IModelDoc2 document = component.GetModelDoc2() as IModelDoc2;
            if (document == null) {
                throw new InvalidOperationException("Component is not fully loaded/resolved: " + occurrence + ". Resolve it manually and rerun; no partial CSV is written.");
            }
            string configuration = component.ReferencedConfiguration ?? "";
            bool asItem = String.Equals(Property(document, configuration, new string[]{"CF_ExportAsItem"}, result), "true", StringComparison.OrdinalIgnoreCase);
            if (document.GetType() == 2 && !asItem) {
                Array children = component.GetChildren() as Array;
                if (children == null || children.Length == 0) {
                    throw new InvalidOperationException("Assembly has no accessible children: " + occurrence + ". Fully resolve it or explicitly set CF_ExportAsItem=true for a purchased assembly.");
                }
                foreach (object child in children) Walk((IComponent2)child, multiplier, result, groups, depth + 1);
                return;
            }
            string source = component.GetPathName();
            if (String.IsNullOrWhiteSpace(source)) {
                throw new InvalidOperationException("Component has no stable path: " + occurrence + ". Save the assembly and virtual components first.");
            }
            string key = source + "|" + configuration;
            PartRow row;
            if (groups.TryGetValue(key, out row)) {
                row.quantity = checked(row.quantity + multiplier);
                row.source_reference += "; " + occurrence;
                return;
            }
            row = new PartRow();
            using (SHA256 hash = SHA256.Create()) {
                byte[] digest = hash.ComputeHash(Encoding.UTF8.GetBytes(key.ToUpperInvariant()));
                row.id = "sw-" + BitConverter.ToString(digest).Replace("-", "").Substring(0, 20).ToLowerInvariant();
            }
            row.part_number = Property(document, configuration, new string[]{"CF_PartNumber", "PartNumber", "零件编号", "图号"}, result);
            row.name = Property(document, configuration, new string[]{"CF_Name", "Description", "名称", "零件名称"}, result);
            if (String.IsNullOrWhiteSpace(row.name)) row.name = Path.GetFileNameWithoutExtension(source) + " [" + configuration + "]";
            row.material = Property(document, configuration, new string[]{"CF_Material", "Material", "材料", "材质"}, result);
            row.category = Category(Property(document, configuration, new string[]{"CF_Category", "category", "工艺分类"}, result), result, occurrence);
            row.finish = Property(document, configuration, new string[]{"CF_Finish", "Finish", "表面处理", "饰面"}, result);
            row.length_mm = Dimension(Property(document, configuration, new string[]{"CF_CutLength_mm", "下料长度mm"}, result), "length", occurrence, result);
            row.width_mm = Dimension(Property(document, configuration, new string[]{"CF_CutWidth_mm", "下料宽度mm"}, result), "width", occurrence, result);
            row.thickness_mm = Dimension(Property(document, configuration, new string[]{"CF_CutThickness_mm", "下料厚度mm"}, result), "thickness", occurrence, result);
            row.revision = Property(document, configuration, new string[]{"CF_Revision", "Revision", "版本", "修订"}, result);
            row.source_file = source;
            row.source_reference = "configuration=" + configuration + "; occurrences=" + occurrence;
            row.quantity = multiplier;
            groups.Add(key, row);
        }

        private static string Property(IModelDoc2 model, string configuration, string[] aliases, ExportResult result) {
            string[] scopes = String.IsNullOrEmpty(configuration) ? new string[]{""} : new string[]{configuration, ""};
            foreach (string scope in scopes) {
                ICustomPropertyManager manager = model.Extension.CustomPropertyManager[scope];
                foreach (string name in aliases) {
                    ReadValue read = ReadProperty(manager, name, result, model.GetPathName() + " [" + scope + "]");
                    if (read.found) return read.value;
                }
            }
            return "";
        }

        private static ReadValue ReadProperty(ICustomPropertyManager manager, string name, ExportResult result, string source) {
            string raw, evaluated;
            bool wasResolved, linked;
            manager.Get6(name, true, out raw, out evaluated, out wasResolved, out linked);
            ReadValue read = new ReadValue();
            read.found = !String.IsNullOrWhiteSpace(raw) || !String.IsNullOrWhiteSpace(evaluated);
            if (!read.found) return read;
            if (!wasResolved) {
                result.warnings.Add("Unresolved cached property left blank: " + source + " / " + name);
                return read;
            }
            read.value = (String.IsNullOrWhiteSpace(evaluated) ? raw : evaluated).Trim();
            return read;
        }

        private static string Dimension(string raw, string dimension, string occurrence, ExportResult result) {
            if (String.IsNullOrWhiteSpace(raw)) return "";
            string normalized = Regex.Replace(raw.Trim(), @"\s*(mm|毫米)\s*$", "", RegexOptions.IgnoreCase);
            double value;
            if (!Double.TryParse(normalized, NumberStyles.AllowDecimalPoint | NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out value) || Double.IsNaN(value) || Double.IsInfinity(value) || value <= 0) {
                result.warnings.Add("Invalid explicit millimetre cut dimension left blank: " + occurrence + " / " + dimension + "=" + raw);
                return "";
            }
            return value.ToString("0.########", CultureInfo.InvariantCulture);
        }

        private static string Category(string raw, ExportResult result, string occurrence) {
            switch ((raw ?? "").Trim().ToLowerInvariant()) {
                case "wood": case "木工": case "木制": return "wood";
                case "metal": case "五金": case "金属": return "metal";
                case "glass": case "玻璃": return "glass";
                case "electrical": case "电气": case "电工": return "electrical";
                case "hardware": case "标准件": case "外购件": return "hardware";
                case "": return "";
                default: result.warnings.Add("Unknown category left blank: " + occurrence + " / " + raw); return "";
            }
        }
    }
}
'@

if (-not ('CabinetFlowBridge.Reader' -as [type])) {
    Add-Type -TypeDefinition $bridgeSource -ReferencedAssemblies @($InteropPath, 'System.dll', 'System.Core.dll')
}
try {
    $application = [Runtime.InteropServices.Marshal]::GetActiveObject('SldWorks.Application')
} catch {
    throw 'No accessible running SOLIDWORKS instance. Open SOLIDWORKS and the assembly as the same Windows user, without a mismatched administrator session.'
}
$result = [CabinetFlowBridge.Reader]::Read($application, $AssemblyQuantity)
$directory = [IO.Path]::GetDirectoryName($OutputCsv)
[void][IO.Directory]::CreateDirectory($directory)
$columns = @('id', 'part_number', 'name', 'material', 'category', 'length_mm', 'width_mm', 'thickness_mm', 'quantity', 'unit', 'finish', 'source_file', 'source_reference', 'revision')
$temporaryCsv = $OutputCsv + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
try {
    $result.rows | Select-Object -Property $columns | Export-Csv -LiteralPath $temporaryCsv -NoTypeInformation -Encoding UTF8
    Move-Item -LiteralPath $temporaryCsv -Destination $OutputCsv -Force:$Force
} finally {
    if (Test-Path -LiteralPath $temporaryCsv) { Remove-Item -LiteralPath $temporaryCsv }
}
$audit = [ordered]@{
    bridge_version = '1.0.0'
    exported_at_utc = [DateTime]::UtcNow.ToString('o')
    assembly_file = $result.assembly_file
    configuration = $result.configuration
    assembly_quantity = $AssemblyQuantity
    exported_rows = $result.rows.Count
    suppressed_instances = $result.suppressed_instances
    csv_sha256 = (Get-FileHash -LiteralPath $OutputCsv -Algorithm SHA256).Hash.ToLowerInvariant()
    review_status = 'pending'
    warnings = @($result.warnings.ToArray())
}
$audit | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $auditPath -Encoding UTF8
Write-Output "Exported $($result.rows.Count) part rows: $OutputCsv"
Write-Output "Audit and limitations: $auditPath"
Write-Output 'Import into Cabinet Flow and review the released BOM, quantities, cut sizes and process categories before approving tasks.'
