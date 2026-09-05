// Captioned concept film. No live purchase, vendor lookup or payment is performed.
const sharp=require('/Users/alberto/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');
const W=1280,H=720,FPS=24,DURATION=42;const out=path.join(__dirname,'relay-broker-concept.mp4');
const C={paper:'#EEF0E9',ink:'#182234',soft:'#65706C',green:'#2F6F4E',wash:'#DFE8DD',rust:'#9C5330',line:'#B9C3B6'};
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const txt=(x,y,s,size=24,fill=C.ink,weight=400,anchor='start')=>`<text x="${x}" y="${y}" font-family="Arial, sans-serif" font-size="${size}" fill="${fill}" font-weight="${weight}" text-anchor="${anchor}">${esc(s)}</text>`;
const rect=(x,y,w,h,fill=C.wash,stroke='none',r=0)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}"/>`;
const line=(x,y,a,b,color=C.line,width=2,dash='')=>`<line x1="${x}" y1="${y}" x2="${a}" y2="${b}" stroke="${color}" stroke-width="${width}" ${dash?`stroke-dasharray="${dash}"`:''}/>`;
const arrow=(x,y,a,b)=>line(x,y,a,b,C.green,3)+`<path d="M${a-10},${b-6} L${a},${b} L${a-10},${b+6}" fill="none" stroke="${C.green}" stroke-width="3"/>`;
const ease=x=>1-Math.pow(1-Math.max(0,Math.min(1,x)),3);
const enter=(t,delay,content)=>{let v=ease((t-delay)/.6);return `<g opacity="${v}" transform="translate(0 ${18*(1-v)})">${content}</g>`};
const heading=(k,title,sub)=>txt(70,135,k,17,C.green,700)+txt(70,203,title,47,C.ink,700)+txt(70,247,sub,23,C.soft);
function frame(time){let n=Math.min(6,Math.floor(time/6)),t=time-n*6;let q='';
if(n===0){q=heading('RELAY / THE PROCUREMENT BROKER','Tell us what you need.','Relay selects a supplier and handles the small purchase.');
q+=enter(t,.3,rect(70,307,470,242,C.wash)+txt(98,349,'YOUR APP OR AGENT',16,C.green,700)+txt(98,402,'“Find the data I need,',30,C.ink,700)+txt(98,446,'within my budget.”',30,C.ink,700)+txt(98,510,'One request. Clear constraints.',22,C.soft));
q+=enter(t,1,arrow(566,423,697,423)+rect(731,324,450,208,'none',C.green)+txt(765,380,'RELAY',20,C.green,700)+txt(765,427,'Select → purchase → deliver',27,C.ink,700)+txt(765,479,'A proxy between apps and suppliers.',20,C.soft));}
if(n===1){q=heading('01 / START WITH THE REQUIREMENT','A useful match comes first.','For example: supplemental context for a personal loan review.');
let items=[['DATA NEEDED','Industry income context'],['COVERAGE','United States · legal services'],['LIMITS','Freshness requirement + spend cap']];
items.forEach((v,i)=>q+=enter(t,.2+i*.6,line(70,301+i*87,1195,301+i*87)+txt(85,350+i*87,v[0],17,C.green,700)+txt(390,350+i*87,v[1],29,C.ink,500)));
q+=enter(t,2.4,txt(70,609,'The application defines the need. Relay handles procurement.',24,C.soft));}
if(n===2){q=heading('02 / SELECT THE SUPPLIER','The cheapest offer may be the wrong one.','Match the requirement first. Compare eligible quotes second.');
q+=txt(88,302,'ILLUSTRATIVE OFFERS',16,C.soft,700)+txt(636,302,'PER REQUEST',16,C.soft,700)+txt(906,302,'MATCH RESULT',16,C.soft,700);
let rows=[['Supplier A','0.040 XRP','Eligible',C.ink],['Supplier B','0.020 XRP',t>2.8?'Selected':'Eligible',C.green],['Supplier C','0.006 XRP','Wrong coverage',C.rust]];
rows.forEach((v,i)=>q+=enter(t,.25+i*.55,rect(70,323+i*77,1130,69,i===1&&t>2.8?C.wash:'none')+line(70,393+i*77,1200,393+i*77)+txt(88,366+i*77,v[0],28)+txt(640,366+i*77,v[1],28,v[3],700)+txt(907,366+i*77,v[2],25,v[3],700)));
q+=enter(t,3.3,txt(70,613,'0.020 XRP: 50% below the other eligible quote in this example.',23,C.green,700));}
if(n===3){q=heading('03 / AUTOMATE THE PURCHASE','One integration. Less repeated buying work.','The broker coordinates the request, the supplier and the payment.');
let steps=[['SELECT','Apply customer rules'],['AUTHORIZE','Respect the spend cap'],['PURCHASE','Use an accepted rail'],['RETURN','Result + receipt']];
steps.forEach((v,i)=>{let x=70+i*293; q+=enter(t,.2+i*.6,txt(x,350,`0${i+1}`,46,C.green,700)+line(x,380,x+240,380,C.green)+txt(x,428,v[0],22,C.ink,700)+txt(x,470,v[1],19,C.soft));if(i<3)q+=enter(t,.6+i*.6,arrow(x+245,363,x+274,363));});
q+=enter(t,3,rect(70,535,1130,77,C.wash)+txt(95,584,'No qualifying supplier? Stop before spending.',28,C.green,700));}
if(n===4){q=heading('04 / KEEP SETTLEMENT BEHIND THE SCENES','Customer pays in dollars. Relay handles the rails.','Proposed experience: familiar USD billing, supplier-compatible settlement.');
q+=enter(t,.2,rect(70,331,310,171,C.wash)+txt(97,371,'CUSTOMER',16,C.green,700)+txt(97,422,'USD',44,C.ink,700)+txt(97,468,'No wallet in the user flow',20,C.soft));
q+=enter(t,.8,arrow(395,417,481,417)+rect(497,331,263,171,'none',C.green)+txt(525,371,'RELAY',16,C.green,700)+txt(525,422,'Broker',39,C.ink,700)+txt(525,468,'Selects payment route',19,C.soft));
q+=enter(t,1.4,arrow(777,417,863,417)+txt(885,361,'SUPPLIER ACCEPTS',16,C.green,700)+txt(885,405,'XRP / supported crypto',23,C.ink,700)+txt(885,448,'or a fiat payment route',23,C.ink,700)+txt(885,487,'Confirm currency + network',19,C.soft));
q+=enter(t,2.5,rect(70,549,1130,70,C.wash)+txt(93,591,'XRPL: fast ledger confirmation and low ledger fees for supported routes.',23,C.green,700));}
if(n===5){q=heading('05 / CLOSE THE LOOP','A result. A receipt. A purchase you can trace.','Keep delivery and payment status visible to the calling application.');
q+=enter(t,.2,rect(70,313,575,270,C.wash)+txt(96,355,'PURCHASE RECORD',17,C.green,700)+txt(96,405,'Selected supplier + resource',26)+txt(96,452,'Amount + delivery status',26)+txt(96,499,'Payment receipt + transaction hash',26)+txt(96,548,'No need to expose chain details to the user.',19,C.soft));
q+=enter(t,1,txt(710,364,'WORKING DEMO',17,C.green,700)+txt(710,408,'XRP Testnet payment',28,C.ink,700)+txt(710,450,'Fixed sample delivery',28,C.ink,700)+txt(710,510,'A payment receipt proves payment.',21,C.soft)+txt(710,544,'Data quality needs separate evidence.',21,C.soft));}
if(n===6){q=txt(70,164,'RELAY',25,C.green,700)+txt(70,248,'Your demand. Our procurement.',52,C.ink,700)+txt(70,296,'Supplier selection + automated small purchases',29,C.soft);
q+=enter(t,.3,line(70,348,1200,348)+txt(70,400,'Buy the right resource.',31,C.green,700)+txt(70,448,'Compare eligible prices.',31,C.green,700)+txt(70,496,'Keep settlement out of the way.',31,C.green,700));
q+=enter(t,1.3,rect(733,379,467,183,C.wash)+txt(757,418,'START WITH ONE USE CASE',16,C.green,700)+txt(757,462,'Underwriting data today.',27,C.ink,700)+txt(757,503,'Broader API procurement next.',25,C.ink,700)+txt(757,539,'Platform vision; expansion remains planned.',17,C.soft));
q+=txt(70,618,'Planned: USD collection, multi-rail routing and richer supplier matching.',20,C.soft);}
let fade=Math.min(ease(t/.45),ease((6-t)/.4));
let foot=n===4?'PRODUCT CONCEPT · USD collection, conversion and multi-rail routing are not implemented.':n===2?'CONCEPT DEMO · Fictional comparison quotes; not live vendor offers or measured savings.':'CONCEPT DEMO · Illustrative broker workflow. Working implementation: XRP Testnet + supplier samples.';
return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><rect width="1280" height="720" fill="${C.paper}"/>${Array.from({length:18},(_,i)=>line(0,40*i,1280,40*i,'#E4E8DF',1)).join('')}${line(49,0,49,720,'#D8DFD2',1)}${txt(70,51,'RELAY',19,C.green,700)}${txt(1200,51,'SUPPLIER SELECTION / SMALL PURCHASES',13,C.soft,400,'end')}<g opacity="${fade}">${q}</g>${line(70,650,1200,650)}${txt(70,680,foot,14,C.soft)}${rect(0,711,1280,9,'#DCE2D6')}${rect(0,711,1280*time/DURATION,9,C.green)}</svg>`;
}
(async()=>{let ff=spawn('/opt/homebrew/bin/ffmpeg',['-y','-f','image2pipe','-vcodec','png','-framerate',String(FPS),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-movflags','+faststart',out],{stdio:['pipe','ignore','pipe']});let err='';ff.stderr.on('data',d=>err+=d);const finished=new Promise((resolve,reject)=>{ff.on('error',reject);ff.on('close',c=>c===0?resolve():reject(new Error(err)))});
for(let i=0;i<FPS*DURATION;i++){let png=await sharp(Buffer.from(frame(i/FPS))).png().toBuffer();if(!ff.stdin.write(png))await new Promise(r=>ff.stdin.once('drain',r));if(i%(FPS*6)===FPS*3)await sharp(png).toFile(path.join(__dirname,`preview-${Math.floor(i/(FPS*6))+1}.png`));if(i%(FPS*6)===0)console.log(`Rendering scene ${i/(FPS*6)+1}/7`);}
ff.stdin.end();await finished;fs.writeFileSync(path.join(__dirname,'relay-broker-storyboard.md'),'# Relay broker concept film\n\n42 seconds, 1280×720, 24 fps. English on-screen captions; intentionally silent.\n\n1. Demand-led procurement.\n2. Define resource, context and budget.\n3. Reject wrong coverage; compare eligible quotes (fictional suppliers).\n4. Automate selection, authorization, purchase and return.\n5. Proposed USD customer experience; supplier-compatible settlement.\n6. Result and receipt; current Testnet boundary.\n7. Platform promise and first use case.\n\nAll quote comparisons are illustrative. USD collection, currency conversion and multi-rail routing are planned, not current capabilities. Ledger speed/fees are not end-to-end cost or latency measurements. No voiceover or music.\n\nSources: existing demo implementation and https://xrpl.org/about/xrp for ledger payment properties.\n');console.log(out);})();
