const XLSX_HEADERS=['شماره تانک','گونه','بیومس','تعداد','میانگین وزن','غذادهی (g)','سایز غذا','دفعات غذادهی','درصد غذادهی','دما','نوع داروی مصرفی','دوز دارو','نوع مکمل','دوز مکمل','اکسیژن','pH','تعداد روز قبل','تعداد تلفات','بیومس روز قبل','سن ماهی (روز)','سورت','تاریخ ورود'];
const XLSX_KEYS=['tank','species','biomass','count','avg_weight','feed_g','feed_size','feedings','feed_pct','temperature','medicine','medicine_dose','supplement','supplement_dose','oxygen','ph','prev_count','mortality','prev_biomass','age_days','sort','entry_date'];
const XLSX_STYLES=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0"/><numFmt numFmtId="165" formatCode="#,##0.00"/></numFmts>
<fonts count="4"><font><sz val="11"/><name val="Arial"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="16"/><name val="Arial"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/></font></fonts>
<fills count="5"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF0F766E"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FF2F7F72"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE5F4EF"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border><border><left style="thin"><color rgb="FF9FB3AD"/></left><right style="thin"><color rgb="FF9FB3AD"/></right><top style="thin"><color rgb="FF9FB3AD"/></top><bottom style="thin"><color rgb="FF9FB3AD"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="11">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" readingOrder="2"/></xf>
<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="right" vertical="center" wrapText="1" readingOrder="2"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" readingOrder="2"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1" readingOrder="2"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1" readingOrder="2"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"/>
<xf numFmtId="0" fontId="3" fillId="4" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center" readingOrder="2"/></xf>
<xf numFmtId="165" fontId="3" fillId="4" borderId="1" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`;

function xesc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function colName(n){let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26)}return s}
function isFiniteNumber(v){return typeof v==='number'&&Number.isFinite(v)}
function xcell(ref,v,style=5){if(v==null||v===''||(typeof v==='string'&&v.startsWith('#')))return `<c r="${ref}" s="${style}"/>`;if(isFiniteNumber(v))return `<c r="${ref}" s="${style}"><v>${v}</v></c>`;return `<c r="${ref}" s="${style}" t="inlineStr"><is><t xml:space="preserve">${xesc(v)}</t></is></c>`}
function xTotal(tanks,key){let vals=tanks.map(t=>t[key]).filter(isFiniteNumber);if(['biomass','count','feed_g','prev_count','mortality','prev_biomass'].includes(key))return vals.reduce((a,b)=>a+b,0);if(key==='avg_weight'){let c=tanks.reduce((s,t)=>s+(isFiniteNumber(t.count)?t.count:0),0),b=tanks.reduce((s,t)=>s+(isFiniteNumber(t.biomass)?t.biomass:0),0);return c?b/c:null}if(key==='feed_pct'){let pb=tanks.reduce((s,t)=>s+(isFiniteNumber(t.prev_biomass)?t.prev_biomass:0),0),fg=tanks.reduce((s,t)=>s+(isFiniteNumber(t.feed_g)?t.feed_g:0),0);return pb?fg/pb*100:null}if(['temperature','oxygen','ph'].includes(key))return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null;return null}
function xSheetXml(r){let rows=[],merges=['A1:V1'];const add=(rr,cells)=>rows.push(`<row r="${rr}" ht="24" customHeight="1">${cells.join('')}</row>`);
add(1,[xcell('A1','گزارش روزانه نرسری و قرنطینه',1)]);
add(3,[xcell('A3','شماره گزارش',2),xcell('C3',r.report_no,3),xcell('H3','حداقل دمای قرنطینه',2),xcell('K3',r.q_min_temp,3),xcell('M3','حداقل دمای نرسری',2),xcell('O3',r.n_min_temp,3),xcell('R3','تاریخ',2),xcell('S3',r.date,3)]);
add(4,[xcell('H4','حداکثر دمای قرنطینه',2),xcell('K4',r.q_max_temp,3),xcell('M4','حداکثر دمای نرسری',2),xcell('O4',r.n_max_temp,3)]);
add(5,[xcell('H5','آمونیاک',2),xcell('K5',r.q_ammonia,3),xcell('M5','آمونیاک',2),xcell('O5',r.n_ammonia,3)]);
add(6,[xcell('H6','نیتریت',2),xcell('K6',r.q_nitrite,3),xcell('M6','نیتریت',2),xcell('O6',r.n_nitrite,3)]);
let rr=8,tanks=Array.isArray(r.tanks)?r.tanks:[];
for(const g of ['H','Q','N']){let gt=tanks.filter(t=>String(t.tank||'').startsWith(g));if(!gt.length)continue;
 add(rr,XLSX_HEADERS.map((h,i)=>xcell(`${colName(i+1)}${rr}`,h,4)));rr++;
 for(const t of gt){add(rr,XLSX_KEYS.map((k,i)=>{let st=['biomass','avg_weight','feed_g','feed_pct','temperature','oxygen','ph','prev_biomass'].includes(k)?7:(['count','feedings','prev_count','mortality'].includes(k)?6:5);return xcell(`${colName(i+1)}${rr}`,t[k],st)}));rr++}
 add(rr,XLSX_KEYS.map((k,i)=>{let v=i===0?'مجموع':i===1?'sea bass':xTotal(gt,k),st=i<=1?9:(isFiniteNumber(v)?10:9);return xcell(`${colName(i+1)}${rr}`,v,st)}));rr+=2;
}
let widths=[11,14,15,12,14,14,11,13,14,10,19,14,16,14,11,10,15,14,16,14,14,15],cols=widths.map((w,i)=>`<col min="${i+1}" max="${i+1}" width="${w}" customWidth="1"/>`).join('');
return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0" rightToLeft="1"><pane ySplit="7" topLeftCell="A8" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="20"/><cols>${cols}</cols><sheetData>${rows.join('')}</sheetData><mergeCells count="${merges.length}">${merges.map(m=>`<mergeCell ref="${m}"/>`).join('')}</mergeCells><pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/><pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>`}
function xSheetName(r,i,used){let s=String(r.date||`گزارش-${i}`).replaceAll('/','-').replace(/[\\?*:[\]]/g,'-').slice(0,31)||`گزارش-${i}`,base=s,n=2;while(used.has(s)){let suf='-'+n++;s=base.slice(0,31-suf.length)+suf}used.add(s);return s}
function u8(s){return new TextEncoder().encode(s)}
let CRC_TABLE=null;function crc32(a){if(!CRC_TABLE){CRC_TABLE=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=(c&1)?0xedb88320^(c>>>1):c>>>1;CRC_TABLE[n]=c>>>0}}let c=0xffffffff;for(let i=0;i<a.length;i++)c=CRC_TABLE[(c^a[i])&255]^(c>>>8);return (c^0xffffffff)>>>0}
function le16(n){return Uint8Array.of(n&255,(n>>>8)&255)}function le32(n){return Uint8Array.of(n&255,(n>>>8)&255,(n>>>16)&255,(n>>>24)&255)}
function cat(parts){let n=parts.reduce((s,a)=>s+a.length,0),o=new Uint8Array(n),p=0;for(const a of parts){o.set(a,p);p+=a.length}return o}
function zipStore(entries){let locals=[],centrals=[],offset=0;for(const e of entries){let name=u8(e.name),data=typeof e.data==='string'?u8(e.data):e.data,crc=crc32(data),lh=cat([le32(0x04034b50),le16(20),le16(0x0800),le16(0),le16(0),le16(0),le32(crc),le32(data.length),le32(data.length),le16(name.length),le16(0),name,data]);locals.push(lh);let ch=cat([le32(0x02014b50),le16(20),le16(20),le16(0x0800),le16(0),le16(0),le16(0),le32(crc),le32(data.length),le32(data.length),le16(name.length),le16(0),le16(0),le16(0),le16(0),le32(0),le32(offset),name]);centrals.push(ch);offset+=lh.length}let central=cat(centrals),body=cat(locals),end=cat([le32(0x06054b50),le16(0),le16(0),le16(entries.length),le16(entries.length),le32(central.length),le32(body.length),le16(0)]);return cat([body,central,end])}
function buildXlsxBytes(list){let rs=list.filter(r=>r&&r.date&&Array.isArray(r.tanks));if(!rs.length)throw Error('گزارشی برای خروجی وجود ندارد');let used=new Set(),sheets=rs.map((r,i)=>({r,name:xSheetName(r,i+1,used)})),rels=[],ct=[],sn=[];for(let i=0;i<sheets.length;i++){let n=i+1;sn.push(`<sheet name="${xesc(sheets[i].name)}" sheetId="${n}" r:id="rId${n}"/>`);rels.push(`<Relationship Id="rId${n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${n}.xml"/>`);ct.push(`<Override PartName="/xl/worksheets/sheet${n}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`)}rels.push(`<Relationship Id="rId${sheets.length+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`);
let workbook=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView/></bookViews><sheets>${sn.join('')}</sheets><calcPr calcId="191029"/></workbook>`;
let wbrels=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels.join('')}</Relationships>`;
let types=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${ct.join('')}<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>`;
let rootrels=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>`;
let core=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>Nursery Daily</dc:creator><cp:lastModifiedBy>Nursery Daily</cp:lastModifiedBy></cp:coreProperties>`;
let app=`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Nursery Daily</Application></Properties>`;
let entries=[{name:'[Content_Types].xml',data:types},{name:'_rels/.rels',data:rootrels},{name:'docProps/core.xml',data:core},{name:'docProps/app.xml',data:app},{name:'xl/workbook.xml',data:workbook},{name:'xl/_rels/workbook.xml.rels',data:wbrels},{name:'xl/styles.xml',data:XLSX_STYLES}];sheets.forEach((s,i)=>entries.push({name:`xl/worksheets/sheet${i+1}.xml`,data:xSheetXml(s.r)}));return zipStore(entries)}
function bytesToBase64(bytes){let chunk=0x8000,out='';for(let i=0;i<bytes.length;i+=chunk)out+=String.fromCharCode(...bytes.subarray(i,Math.min(i+chunk,bytes.length)));return btoa(out)}
function downloadBinary(name,bytes,mime){if(window.AndroidBridge&&AndroidBridge.saveBase64File){AndroidBridge.saveBase64File(name,bytesToBase64(bytes),mime);return}let a=document.createElement('a'),url=URL.createObjectURL(new Blob([bytes],{type:mime}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1500)}
function exportLatestXlsx(){try{let r=reports.length?reports[reports.length-1]:null;if(!r)return toast('اول یک گزارش ذخیره کن');let bytes=buildXlsxBytes([r]);downloadBinary(`nursery_${r.date.replaceAll('/','-')}.xlsx`,bytes,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');toast('فایل Excel آماده شد')}catch(e){toast('خطا در ساخت Excel: '+e.message)}}
function exportAllXlsx(){try{if(!reports.length)return toast('هنوز گزارشی داخل اپ ذخیره نشده');let bytes=buildXlsxBytes(reports);downloadBinary(`nursery_all_reports.xlsx`,bytes,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');toast(`${reports.length} گزارش در Excel آماده شد`)}catch(e){toast('خطا در ساخت Excel: '+e.message)}}

(function installExcelButtons(){
  const actions=document.querySelector('#data .data-actions');
  if(actions&&!document.getElementById('excelLatestBtn')){
    const latest=document.createElement('button');
    latest.id='excelLatestBtn';latest.className='btn';latest.textContent='Excel آخرین گزارش';latest.onclick=exportLatestXlsx;
    const all=document.createElement('button');
    all.id='excelAllBtn';all.className='btn alt';all.textContent='Excel همه گزارش‌ها';all.onclick=exportAllXlsx;
    actions.prepend(all);actions.prepend(latest);
  }
  const version=document.querySelector('header .top > small');
  if(version)version.textContent='v1.2';
})();
