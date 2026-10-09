#requires -Version 5.1
<#
.SYNOPSIS
Export the active, fully resolved SOLIDWORKS assembly as a separate STEP package.
.DESCRIPTION
Windows PowerShell 5.1 x64/STA and installed SOLIDWORKS 2024+ interop DLLs.
Does not open/resolve/rebuild/switch configurations or save native source documents.
Uses the native STEP exporter, never BOM-derived boxes or guessed transforms.
This script has NOT been executed against a licensed SOLIDWORKS installation.
The native export may fire FileSaveNotify and update in-memory preview state.
Read MODEL-EXPORT.md for the exact verification boundary before first deployment.
.EXAMPLE
powershell.exe -NoProfile -STA -File .\Export-SolidWorksModel.ps1 -OutputDirectory C:\CabinetFlow\order-001-model
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$InteropPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess) {
    throw 'Use 64-bit Windows PowerShell 5.1 (powershell.exe), not PowerShell 7/macOS.'
}
if ([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') { throw 'Start powershell.exe with -STA.' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $OutputDirectory) { throw 'OutputDirectory must be a NEW directory. Existing output is never overwritten.' }
if (-not $InteropPath) {
    foreach ($root in @((Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS\api\redist'), (Join-Path $env:ProgramFiles 'SOLIDWORKS Corp\SOLIDWORKS'))) {
        $candidate = Join-Path $root 'SolidWorks.Interop.sldworks.dll'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $InteropPath = $candidate; break }
    }
}
if (-not $InteropPath -or -not (Test-Path -LiteralPath $InteropPath -PathType Leaf)) { throw 'Supply the installed SOLIDWORKS 2024+ SolidWorks.Interop.sldworks.dll with -InteropPath.' }
$InteropPath = (Resolve-Path -LiteralPath $InteropPath).Path
$constantPath = Join-Path ([IO.Path]::GetDirectoryName($InteropPath)) 'SolidWorks.Interop.swconst.dll'
if (-not (Test-Path -LiteralPath $constantPath -PathType Leaf)) { throw 'The matching SolidWorks.Interop.swconst.dll must be beside sldworks.dll.' }
[void][Reflection.Assembly]::LoadFrom($InteropPath)
[void][Reflection.Assembly]::LoadFrom($constantPath)
$bridgeSource = @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

namespace CabinetFlowModelBridge {
    public sealed class Occurrence {
        public string occurrence_id, parent_occurrence_id, occurrence_name, source_file, configuration;
        public string bom_id, part_number, type;
        public bool suppressed, hidden, export_as_item;
    }
    public sealed class SourceState {
        public string path, sha256_before, sha256_after, active_configuration;
        public bool dirty_before, dirty_after;
        internal IModelDoc2 document;
    }
    public sealed class Result {
        public string assembly_file, configuration, solidworks_revision;
        public string geometry_origin = "SOLIDWORKS native STEP translator";
        public int step_ap, export_errors, export_warnings;
        public bool face_edge_properties, split_periodic_faces, atomic_save;
        public string output_coordinate_system;
        public List<Occurrence> occurrences = new List<Occurrence>();
        public List<SourceState> sources = new List<SourceState>();
    }
    public static class Exporter {
        static string HashText(string key, string prefix) {
            using (SHA256 hash = SHA256.Create()) {
                return prefix + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(key.ToUpperInvariant()))).Replace("-", "").Substring(0,20).ToLowerInvariant();
            }
        }
        static string HashFile(string path) {
            using (SHA256 hash = SHA256.Create())
            using (FileStream stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)) {
                return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
            }
        }
        static int EnumValue(Type kind, string name) {
            if (!Enum.IsDefined(kind, name)) throw new InvalidOperationException("Installed API cannot verify option " + name + ". Use SOLIDWORKS 2024+ or export STEP manually.");
            return Convert.ToInt32(Enum.Parse(kind, name));
        }
        static void RequireClean(IModelDoc2 model, Result result, Dictionary<string, SourceState> files) {
            string path = model.GetPathName();
            if (String.IsNullOrWhiteSpace(path) || !File.Exists(path)) throw new InvalidOperationException("All source documents must already be saved as regular files; virtual/missing sources are not supported.");
            if (model.GetSaveFlag()) throw new InvalidOperationException("Unsaved source: " + path + ". Manually save and inspect it before rerunning.");
            if (model.Extension.NeedsRebuild2 != (int)swModelRebuildStatus_e.swModelRebuildStatus_FullyRebuilt)
                throw new InvalidOperationException("Source needs rebuild: " + path + ". Rebuild and save manually; bridge will not do this.");
            if (!files.ContainsKey(path)) {
                SourceState state = new SourceState();
                state.path = path; state.document = model; state.active_configuration = model.ConfigurationManager.ActiveConfiguration.Name;
                state.dirty_before = false; state.sha256_before = HashFile(path);
                files.Add(path, state); result.sources.Add(state);
            }
        }
        static string Property(IModelDoc2 model, string configuration, string[] aliases, bool requiredIfPresent) {
            foreach (string scope in new string[]{configuration, ""}) {
                ICustomPropertyManager manager = model.Extension.CustomPropertyManager[scope];
                foreach (string name in aliases) {
                    string raw, evaluated; bool resolved, linked;
                    manager.Get6(name, true, out raw, out evaluated, out resolved, out linked);
                    if (String.IsNullOrWhiteSpace(raw) && String.IsNullOrWhiteSpace(evaluated)) continue;
                    if (!resolved) {
                        if (requiredIfPresent) throw new InvalidOperationException("Cached property is unresolved: " + model.GetPathName() + " / " + configuration + " / " + name);
                        return "";
                    }
                    return (String.IsNullOrWhiteSpace(evaluated) ? raw : evaluated).Trim();
                }
            }
            return "";
        }
        static void Walk(IComponent2 component, string parent, string inheritedBom, Result result, Dictionary<string, SourceState> files, int depth) {
            if (depth > 100) throw new InvalidOperationException("Assembly hierarchy exceeds 100 levels.");
            Occurrence node = new Occurrence();
            node.occurrence_name = component.Name2;
            node.parent_occurrence_id = parent;
            node.occurrence_id = HashText(result.assembly_file + "|" + result.configuration + "|" + component.Name2, "occ-");
            node.source_file = component.GetPathName();
            node.configuration = component.ReferencedConfiguration ?? "";
            int suppression = component.GetSuppression2();
            node.suppressed = suppression == (int)swComponentSuppressionState_e.swComponentSuppressed;
            result.occurrences.Add(node);
            if (node.suppressed) { node.type = "suppressed"; return; }
            if (suppression != (int)swComponentSuppressionState_e.swComponentFullyResolved && suppression != (int)swComponentSuppressionState_e.swComponentResolved)
                throw new InvalidOperationException("Unresolved/lightweight/ID-mismatched component: " + node.occurrence_name);
            if (component.IsSpeedPak) throw new InvalidOperationException("SpeedPak component: " + node.occurrence_name + ". Activate its full configuration manually.");
            IModelDoc2 child = component.GetModelDoc2() as IModelDoc2;
            if (child == null) throw new InvalidOperationException("Component is not fully loaded: " + node.occurrence_name);
            RequireClean(child, result, files);
            // Deliberately conservative: no activating referenced configurations to refresh cached properties.
            if (!String.Equals(child.ConfigurationManager.ActiveConfiguration.Name, node.configuration, StringComparison.Ordinal))
                throw new InvalidOperationException("Referenced configuration differs from loaded active configuration: " + node.occurrence_name + ". This bridge does not switch configurations; use manual STEP export for multi-configuration instances.");
            node.hidden = component.IsHidden(false);
            if (node.hidden) throw new InvalidOperationException("Hidden component has ambiguous STEP visibility: " + node.occurrence_name + ". Show it manually before using this conservative bridge.");
            node.type = child.GetType() == (int)swDocumentTypes_e.swDocASSEMBLY ? "assembly" : "part";
            if (node.type == "part" && child.GetType() != (int)swDocumentTypes_e.swDocPART) throw new InvalidOperationException("Unsupported component document type.");
            if (node.type == "part") {
                Array allBodies = ((IPartDoc)child).GetBodies2((int)swBodyType_e.swAllBodies, false) as Array;
                Array visibleBodies = ((IPartDoc)child).GetBodies2((int)swBodyType_e.swAllBodies, true) as Array;
                if (allBodies == null || allBodies.Length == 0) throw new InvalidOperationException("Part has no accessible B-rep bodies: " + node.occurrence_name);
                if (visibleBodies == null || visibleBodies.Length != allBodies.Length) throw new InvalidOperationException("Part has hidden bodies: " + node.occurrence_name + ". Show all intended bodies manually before export.");
            }
            node.export_as_item = String.Equals(Property(child, node.configuration, new string[]{"CF_ExportAsItem"}, true), "true", StringComparison.OrdinalIgnoreCase);
            string ownBom = HashText(node.source_file + "|" + node.configuration, "sw-");
            node.bom_id = !String.IsNullOrEmpty(inheritedBom) ? inheritedBom : node.type == "part" || node.export_as_item ? ownBom : "";
            node.part_number = Property(child, node.configuration, new string[]{"CF_PartNumber", "PartNumber", "零件编号", "图号"}, false);
            if (node.type == "assembly") {
                Array children = component.GetChildren() as Array;
                if (children == null || children.Length == 0) throw new InvalidOperationException("Subassembly has no accessible children: " + node.occurrence_name);
                foreach (object item in children) Walk((IComponent2)item, node.occurrence_id, node.bom_id, result, files, depth+1);
            }
        }
        public static Result Export(object application, string outputStep) {
            ISldWorks app = (ISldWorks)application;
            IModelDoc2 model = app.ActiveDoc as IModelDoc2;
            if (model == null || model.GetType() != (int)swDocumentTypes_e.swDocASSEMBLY) throw new InvalidOperationException("Activate an already-open assembly.");
            IAssemblyDoc assembly = (IAssemblyDoc)model;
            if (assembly.GetEditTargetComponent() != null) throw new InvalidOperationException("Finish editing the component; activate the top-level assembly.");
            if (((ISelectionMgr)model.SelectionManager).GetSelectedObjectCount2(-1) != 0) throw new InvalidOperationException("Clear the selection manually. Selected faces/bodies would produce a partial STEP.");
            if (model.ConfigurationManager.ActiveConfiguration.IsSpeedPak()) throw new InvalidOperationException("Active assembly configuration is SpeedPak.");
            Result result = new Result();
            result.assembly_file = model.GetPathName(); result.configuration = model.ConfigurationManager.ActiveConfiguration.Name; result.solidworks_revision = app.RevisionNumber();
            Dictionary<string, SourceState> files = new Dictionary<string, SourceState>(StringComparer.OrdinalIgnoreCase);
            RequireClean(model, result, files);
            result.step_ap = app.GetUserPreferenceIntegerValue((int)swUserPreferenceIntegerValue_e.swStepAP);
            int geometry = app.GetUserPreferenceIntegerValue((int)swUserPreferenceIntegerValue_e.swStepExportPreference);
            result.face_edge_properties = app.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swStepExportFaceEdgeProps);
            result.split_periodic_faces = app.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swStepExportSplitPeriodic);
            result.atomic_save = app.GetUserPreferenceToggle(EnumValue(typeof(swUserPreferenceToggle_e), "swStepExportAtomicSave"));
            result.output_coordinate_system = app.GetUserPreferenceStringValue(EnumValue(typeof(swUserPreferenceStringValue_e), "swExportOutputCoordinateSystem"));
            if (result.step_ap != 214) throw new InvalidOperationException("Set STEP AP214 in SOLIDWORKS export options manually.");
            if (geometry != (int)swAcisOutputGeometryPreference_e.swAcisOutputAsSolidAndSurface) throw new InvalidOperationException("Set STEP Output as Solid/Surface geometry manually.");
            if (!result.face_edge_properties) throw new InvalidOperationException("Enable STEP Export face/edge properties manually to retain translator-supported topology properties.");
            if (result.atomic_save) throw new InvalidOperationException("Disable Export assembly components as separate STEP files. Web import requires one self-contained STEP.");
            if (!String.IsNullOrWhiteSpace(result.output_coordinate_system)) throw new InvalidOperationException("Set the STEP output coordinate system to default; a custom transform is not accepted.");
            Array roots = assembly.GetComponents(true) as Array;
            if (roots == null || roots.Length == 0) throw new InvalidOperationException("No accessible assembly components.");
            foreach (object item in roots) Walk((IComponent2)item, "", "", result, files, 0);
            bool hasPart = false; foreach (Occurrence node in result.occurrences) if (node.type == "part") hasPart = true;
            if (!hasPart) throw new InvalidOperationException("No fully loaded, non-suppressed part geometry.");
            if (File.Exists(outputStep)) throw new InvalidOperationException("Output STEP already exists.");
            int errors, warnings;
            // Conversion selected by .step extension. Never SaveReferenced, CopyAndOpen, Save3 or native-file save.
            // Copy/AvoidRebuild flags are native-format options; they are not used as a STEP safety guarantee.
            bool ok = model.Extension.SaveAs3(outputStep, (int)swSaveAsVersion_e.swSaveAsCurrentVersion,
                (int)swSaveAsOptions_e.swSaveAsOptions_Silent, null, null, out errors, out warnings);
            result.export_errors = errors; result.export_warnings = warnings;
            if (!ok || errors != 0 || warnings != 0) throw new InvalidOperationException("STEP export requires review: errors=" + errors + ", warnings=" + warnings + ". No verified package is published.");
            IModelDoc2 after = app.ActiveDoc as IModelDoc2;
            if (after == null || !String.Equals(after.GetPathName(), result.assembly_file, StringComparison.OrdinalIgnoreCase) || after.ConfigurationManager.ActiveConfiguration.Name != result.configuration)
                throw new InvalidOperationException("The active document/configuration changed during STEP export.");
            foreach (SourceState source in result.sources) {
                source.sha256_after = HashFile(source.path); source.dirty_after = source.document.GetSaveFlag();
                if (source.sha256_before != source.sha256_after || source.dirty_after || source.document.ConfigurationManager.ActiveConfiguration.Name != source.active_configuration)
                    throw new InvalidOperationException("Source file/state changed during export: " + source.path + ". Inspect SOLIDWORKS manually; no verified package is published.");
            }
            return result;
        }
    }
}
'@
if (-not ('CabinetFlowModelBridge.Exporter' -as [type])) {
    Add-Type -TypeDefinition $bridgeSource -ReferencedAssemblies @($InteropPath, $constantPath, 'System.dll', 'System.Core.dll')
}
try { $application = [Runtime.InteropServices.Marshal]::GetActiveObject('SldWorks.Application') }
catch { throw 'No running SOLIDWORKS instance is accessible. Start SOLIDWORKS under the same Windows user and elevation level.' }
$parent = [IO.Path]::GetDirectoryName($OutputDirectory)
[void][IO.Directory]::CreateDirectory($parent)
$staging = Join-Path $parent ('.cabinetflow-model-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($staging)
try {
    $stepPath = Join-Path $staging 'model.step'
    $result = [CabinetFlowModelBridge.Exporter]::Export($application, $stepPath)
    if (-not (Test-Path -LiteralPath $stepPath -PathType Leaf)) { throw 'SOLIDWORKS did not write a STEP file.' }
    # Structural sanity only, not a geometry/position/tolerance certification.
    $stepText = [IO.File]::ReadAllText($stepPath)
    if (-not $stepText.StartsWith('ISO-10303-21;') -or $stepText -notmatch 'END-ISO-10303-21;' -or $stepText -notmatch 'ADVANCED_FACE\s*\(' -or $stepText -notmatch 'PRODUCT\s*\(') {
        throw 'Export is not a complete STEP with B-rep faces and product records.'
    }
    if ($stepText -match 'EXTERNALLY_DEFINED_REPRESENTATION|DOCUMENT_FILE\s*\(') { throw 'STEP may reference external files; package is not accepted as self-contained.' }
    $productCount = [regex]::Matches($stepText, '\bPRODUCT\s*\(').Count
    $assemblyRelationCount = [regex]::Matches($stepText, '\bNEXT_ASSEMBLY_USAGE_OCCURRENCE\s*\(').Count
    $activeOccurrences = @($result.occurrences | Where-Object { -not $_.suppressed })
    if ($activeOccurrences.Count -gt 1 -and $assemblyRelationCount -eq 0) { throw 'STEP contains no assembly-usage relationships; hierarchy cannot be confirmed.' }
    $indexPath = Join-Path $staging 'occurrences.csv'
    $result.occurrences | Select-Object occurrence_id,parent_occurrence_id,occurrence_name,bom_id,part_number,type,source_file,configuration,suppressed,hidden,export_as_item | Export-Csv -LiteralPath $indexPath -NoTypeInformation -Encoding UTF8
    $audit = [ordered]@{
        bridge_version = '1.0.0-step'
        exported_at_utc = [DateTime]::UtcNow.ToString('o')
        runtime_validation = 'not yet independently validated on a licensed SOLIDWORKS workstation'
        review_status = 'pending_geometry_and_name_review'
        geometry_source = 'Native SOLIDWORKS STEP AP214 translator; no reconstructed boxes or custom transforms'
        unit_policy = 'Read STEP unit declarations in the importer; Web viewer converts supported STEP units to mm. Never assume raw coordinate values are mm.'
        source_verification = 'All loaded source file SHA256 values and active configurations unchanged; dirty flags remained false'
        step_sha256 = (Get-FileHash -LiteralPath $stepPath -Algorithm SHA256).Hash.ToLowerInvariant()
        step_product_records = $productCount
        step_assembly_usage_records = $assemblyRelationCount
        occurrence_index_sha256 = (Get-FileHash -LiteralPath $indexPath -Algorithm SHA256).Hash.ToLowerInvariant()
        result = $result
        mapping_policy = 'bom_id uses the same uppercase source-path|configuration SHA256 prefix as Export-SolidWorksBOM.ps1. STEP mesh order/names are not assumed to equal this index; review and associate in Web.'
        limitations = @('STEP does not preserve the editable SOLIDWORKS feature history.', 'Face/edge properties and native product names are passed through the translator; exact face IDs and complete name matching are not certified.', 'Hidden and suppressed states are recorded; compare actual STEP visibility/occurrences before use.', 'Native export can fire FileSaveNotify and update in-memory previews; no claim of zero UI/session side effects.', 'Export refuses multi-configuration component instances when the loaded active configuration differs from the referenced configuration.')
    }
    $audit | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $staging 'audit.json') -Encoding UTF8
    [IO.Directory]::Move($staging, $OutputDirectory)
    Write-Output "STEP package created: $OutputDirectory"
    Write-Output 'Upload model.step to the same Web project as the BOM; inspect geometry and associate model parts before use.'
} catch {
    # Only the isolated export staging directory is removed; native sources are never touched.
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    throw
}
