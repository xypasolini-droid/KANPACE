const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../static/order-drafts.js'),'utf8');
const context={URL,Map,Set,location:{origin:'http://127.0.0.1:8765'}};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function draftMediaUnique('),source.indexOf('function ensureDraftMedia(')),context);
const hash='a'.repeat(64),otherHash='b'.repeat(64);
const first={id:'cell-8',kind:'产品参考',title:'玻璃立柱 · 清单原图',source_file:'补单.xlsx',sheet:'清单',cell:'C8',url:'/api/drawing-media/assets/one.webp',content_hash:hash};
const second={...first,id:'cell-28',cell:'C28',url:'/api/documents/upload-two/image'};
context.entries=[first,second,{...first,id:'different-pixels',content_hash:otherHash,url:'/api/drawing-media/assets/three.webp'},{...first,id:'unsafe',url:'https://example.com/private.png'}];
const before=JSON.stringify(context.entries),run=expr=>vm.runInContext(expr,context);
const unique=run('draftMediaUnique(entries)');assert.equal(unique.length,2);assert.equal(unique[0].evidence_sources.length,2);assert.equal(JSON.stringify(context.entries),before,'display dedupe must not change evidence data');
context.entry=unique[0];assert.equal(run('draftMediaSource(entry)'),'补单.xlsx · 清单 · C8、C28');assert.equal(unique[1].id,'different-pixels','similar filenames/title do not prove equal content');
context.entries=[{...first,content_hash:null},{...first,id:'same-url',cell:'C28',content_hash:null}];assert.equal(run('draftMediaUnique(entries).length'),1,'same exact resource URL is a safe fallback');
context.entries=[{...first,content_hash:'not-a-hash'},{...second,content_hash:'not-a-hash'}];assert.equal(run('draftMediaUnique(entries).length'),2,'unverified hash must not merge distinct resources');
context.entries=unique;const again=run('draftMediaUnique(entries)');assert.equal(again.length,2);assert.equal(again[0].evidence_sources.length,2,'dedupe is stable and never nests evidence_sources');
// Deduplication is scoped to each gallery/part, so shared images stay visible for every relevant cabinet.
context.entries=[first,second];assert.equal(run('draftMediaUnique(entries).length'),1);context.entries=[first];assert.equal(run('draftMediaUnique(entries).length'),1);
console.log('PASS: identical image pixels dedupe across URLs; distinct pixels and unknown hashes stay separate; merged cell evidence is visible; input records remain unchanged; shared images remain available per part.');
