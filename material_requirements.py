"""BOM net demand and explicit local stock snapshots, never inferred inventory.

Read-only allocation across active orders avoids showing one stock balance as
available to every project. Purchase rows are reviewable drafts, not supplier
orders, stock consumption, or execution release decisions.
"""
import hashlib
import json
import math
import unicodedata
import fulfillment
import production as ledger


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).strip().casefold().split())


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def part_demand(part):
    """Dimensions are net engineering quantities; no stock-sheet yield guessed."""
    qty=part.get('quantity'); material=str(part.get('material') or '').strip()
    if not material or not positive(qty):
        return None, '缺少材料或有效数量'
    length=part.get('length',part.get('length_mm')); width=part.get('width',part.get('width_mm')); thick=part.get('thickness',part.get('thickness_mm'))
    category=part.get('category',''); finish=str(part.get('finish') or '').strip()
    area_categories={'wood','glass','acrylic','board','panel'}
    if category in area_categories:
        if not all(positive(v) for v in (length,width,thick)):
            return None, '板材或玻璃缺少长、宽、厚，无法核算净用量'
        unit='m²'; amount=length*width*qty/1000000
        spec=f'{thick:g} mm · {finish or "表面待核对"}'
        basis='净面积（排版与损耗另行核对）'
    else:
        unit='件';amount=qty
        dimensions=' × '.join(f'{v:g}' for v in (length,width,thick) if positive(v))
        spec=(dimensions+' mm' if dimensions else str(part.get('specification') or part.get('name') or '规格待核对'))+' · '+(finish or '表面待核对')
        basis='按拆单规格计件'
    signature=[normalized(material),normalized(spec),unit,normalized(category)]
    return {'material_key':'mat_'+digest(signature),'name':material,'specification':spec,'unit':unit,'quantity':round(amount,4),'basis':basis,'category':category},None


def scope(project):
    return str(project.get('factory_id') or '')+'|'+str(project.get('factory_type') or 'cabinet')


def build(store,con,project_id=None,factory_type=None,include_demo=False):
    projects=[p for p in store.all(con,'projects') if not p.get('archived') and not fulfillment.is_closed(p) and (include_demo or not p.get('demo')) and (not factory_type or p.get('factory_type','cabinet')==factory_type)]
    if project_id:
        target=ledger.project(store,con,project_id,writable=False)
        projects=[p for p in projects if scope(p)==scope(target)]
    projects.sort(key=lambda p:(p.get('due_date') or '9999-12-31',p['id']))
    grouped={};warnings=[]
    all_parts=store.all(con,'parts')
    for p in projects:
        parts=[x for x in all_parts if x.get('project_id')==p['id'] and not x.get('archived')]
        for part in parts:
            if part.get('revision') is not None and part['revision']!=p.get('revision',1):
                warnings.append({'project_id':p['id'],'part_id':part['id'],'message':str(part.get('name','部件'))+'：构件版次与当前订单不一致，请先完成新版拆单'});continue
            row,error=part_demand(part)
            if error:
                warnings.append({'project_id':p['id'],'part_id':part['id'],'message':str(part.get('name','部件'))+'：'+error});continue
            key=(p['id'],row['material_key'])
            if key not in grouped:
                grouped[key]={**row,'id':'need_'+digest([p['id'],row['material_key']]),'project_id':p['id'],'project_name':p.get('name',''),'factory_scope':scope(p),'revision':p.get('revision',1),'required_quantity':0,'part_ids':[],'part_names':[],'reviewed':True,'need_date':p.get('due_date'),'source_parts':[]}
            r=grouped[key];r['required_quantity']+=row['quantity'];r['part_ids'].append(part['id']);r['part_names'].append(part.get('name','部件'))
            r['reviewed']=r['reviewed'] and part.get('review_status')=='approved'
            r['source_parts'].append([part['id'],part.get('quantity'),part.get('review_status'),row])
    stocks={r['id']:r for r in store.all(con,'inventory_items')}
    balances={};rows=[]
    for r in grouped.values():
        r['required_quantity']=round(r['required_quantity'],4)
        inventory_id='stock_'+digest([r['factory_scope'],r['material_key']]);s=stocks.get(inventory_id)
        available=None if s is None else round(max(0,s['on_hand_quantity']-s['reserved_quantity']),4)
        if inventory_id not in balances:balances[inventory_id]=available
        before=balances[inventory_id]
        allocated=None if before is None else round(min(r['required_quantity'],before),4)
        shortage=None if allocated is None else round(max(0,r['required_quantity']-allocated),4)
        if allocated is not None:balances[inventory_id]=round(before-allocated,4)
        r.update(inventory_id=inventory_id,inventory_version=s.get('version',0) if s else 0,inventory_total=available,inventory_available=before,allocated_quantity=allocated,shortage_quantity=shortage,inventory_record=s)
        r['snapshot']=digest([r['revision'],r.pop('source_parts'),r['inventory_version'],before,shortage])
        rows.append(r)
    if project_id:
        rows=[r for r in rows if r['project_id']==project_id];warnings=[r for r in warnings if r['project_id']==project_id]
    ids={p['id'] for p in projects}
    purchases=[r for r in store.all(con,'purchase_drafts') if r.get('project_id') in ids and (not project_id or r['project_id']==project_id)]
    by_id={r['id']:r for r in rows}
    purchases=[dict(r,stale=(r.get('snapshot')!=by_id.get(r.get('requirement_id'),{}).get('snapshot'))) for r in purchases]
    return {'requirements':rows,'purchases':purchases,'warnings':warnings,'allocation_basis':'按交期分配可用库存，仅用于采购测算；不扣减库存','projects':[{k:p.get(k) for k in ('id','name','revision','factory_type','factory_id')} for p in projects if not project_id or p['id']==project_id]}


def find_requirement(store,con,data):
    p=ledger.project(store,con,data.get('project_id'))
    rows=build(store,con,project_id=p['id'],include_demo=bool(p.get('demo')))['requirements']
    row=next((r for r in rows if r['id']==data.get('requirement_id')),None)
    if not row:ledger.fail('拆单需求已变化，请刷新重新核对',409)
    if data.get('snapshot')!=row['snapshot']:ledger.fail('图纸、数量或库存已更新，请刷新重新核对',409)
    return p,row


def save_inventory(store,con,data):
    p,row=find_requirement(store,con,data)
    old=row['inventory_record'] or {'id':row['inventory_id'],'version':0}
    ledger.expected(old,data)
    onhand=ledger.number(data.get('on_hand_quantity'),'库存现有量')
    reserved=ledger.number(data.get('reserved_quantity',0),'已被其他用途占用量')
    if reserved>onhand:ledger.fail('占用量不能超过现有库存')
    item={**old,'factory_scope':row['factory_scope'],'factory_id':p.get('factory_id'),'factory_type':p.get('factory_type','cabinet'),'material_key':row['material_key'],'name':row['name'],'specification':row['specification'],'unit':row['unit'],'on_hand_quantity':onhand,'reserved_quantity':reserved,'note':ledger.text(data.get('note'),'库存依据',True),'updated_at':ledger.stamp(),'version':old.get('version',0)+1}
    store.put(con,'inventory_items',item)
    store.event(con,p['id'],'inventory_snapshot_saved','核对库存：'+row['name'],inventory_id=item['id'],version=item['version'])
    return {'inventory':item}


def save_purchase(store,con,data):
    p,row=find_requirement(store,con,data)
    if not row['reviewed']:ledger.fail('请先复核关联构件，再生成采购草稿',409)
    if row['shortage_quantity'] is None:ledger.fail('请先核对库存，未知库存不能按零处理',409)
    if row['shortage_quantity']<=0:ledger.fail('当前无净缺口，无需新增采购草稿',409)
    identifier='buy_'+digest([p['id'],row['material_key']]);old=next((r for r in store.all(con,'purchase_drafts') if r['id']==identifier),None)
    qty=ledger.number(data.get('quantity',row['shortage_quantity']),'采购数量',positive=True)
    if qty<row['shortage_quantity']:ledger.fail('采购数量小于净缺口，请核对采购单位或分批计划')
    note=ledger.text(data.get('note'),'采购说明');supplier=ledger.text(data.get('supplier'),'供应商',limit=200)
    if old and old.get('snapshot')==row['snapshot'] and (old['quantity'],old.get('note',''),old.get('supplier',''))==(qty,note,supplier):
        return {'purchase':old,'duplicate':True}
    ledger.expected(old or {'version':0},data)
    item={'id':identifier,'requirement_id':row['id'],'project_id':p['id'],'revision':row['revision'],'material_key':row['material_key'],'name':row['name'],'specification':row['specification'],'unit':row['unit'],'quantity':qty,'net_shortage':row['shortage_quantity'],'snapshot':row['snapshot'],'status':'draft','version':(old or {}).get('version',0)+1,'updated_at':ledger.stamp(),'note':note,'supplier':supplier}
    store.put(con,'purchase_drafts',item);store.event(con,p['id'],'purchase_draft_saved','生成采购草稿：'+row['name'],purchase_id=identifier,version=item['version'])
    return {'purchase':item}
