const assert = require('node:assert/strict');
const {readFileSync, realpathSync} = require('node:fs');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');
const data = JSON.parse(readFileSync('audit-expected.json'));
const f=(v,d)=>new Intl.NumberFormat('tr-TR',{minimumFractionDigits:d,maximumFractionDigits:d}).format(v);
const sign=v=>v<0?'−':v>0?'+':'';
const amount=v=>sign(v)+f(Math.abs(v),1)+' milyar TL';
const pct=v=>sign(v)+'%'+f(Math.abs(v),2);
(async()=>{
 const browser=await chromium.launch();
 try{
  const page=await browser.newPage({viewport:{width:1360,height:850}});
  await page.goto(pathToFileURL(realpathSync('dist/treasury/index.html')).href);
  const cards=page.locator('.card');
  const controls=page.getByLabel('Grafik dönemi');
  for(const scenario of ['weekly','13','52','custom']){
   if(scenario==='52')await controls.selectOption('52');
   if(scenario==='custom'){
    await controls.selectOption('custom');
    await page.getByLabel('Başlangıç',{exact:true}).fill(data.custom.dates[0]);
    await page.getByLabel('Bitiş',{exact:true}).fill(data.custom.dates[1]);
    await page.getByRole('button',{name:'Uygula'}).click();
   }
   const e=data[scenario], visible=[];
   for(let i=0;i<4;i++){
    const card=cards.nth(i), m=card.locator(scenario==='weekly'?'.metric.weekly':'.period-metric');
    const dates=await m.locator('time').evaluateAll(nodes=>nodes.map(n=>n.dateTime));
    const value=await m.locator('.metric-value').textContent();
    assert.deepEqual(dates,e.dates);
    assert.ok(value.includes(amount(+e.series[i][2])) && value.includes(pct(+e.series[i][3])),value);
    if(scenario==='weekly'){
     const balances=await card.locator('.value').textContent();
     assert.ok(e.series[i].slice(0,2).every(v=>balances.includes(f(+v/1000,1))),balances);
    }
    visible.push(value);
   }
   for(let i=0;i<2;i++){
    const card=cards.nth(i+2), detail=card.locator('.deposit-split');
    if(!(await detail.getAttribute('open')!==null))await detail.locator('summary').click();
    const lines=scenario==='weekly'?(await detail.locator('dd').allTextContents()).join(' · '):
      await detail.locator('.period-deposit-split').textContent();
    assert.ok(e.split[i].every(v=>lines.includes(amount(+v))),lines);
    if(scenario==='weekly')assert.ok((await card.locator('.deposit-reference').textContent()).includes(pct(+e.sector[i])));
    visible.push(lines);
    await detail.locator('summary').click();
   }
   console.log('UI',scenario,JSON.stringify(visible));
  }
  await controls.selectOption('13');
  const slider=cards.first().getByRole('slider');
  await slider.focus();
  await slider.press('Home');
  const tooltip=await cards.first().locator('.tip').textContent();
  const rawStart=new Intl.NumberFormat('tr-TR',{maximumFractionDigits:6}).format(+data['13'].series[0][0]);
  assert.ok(tooltip.includes(rawStart+' milyon TL'),tooltip);
  console.log('TOOLTIP',tooltip);
  await page.getByRole('button',{name:'Karşılaştır',exact:true}).click();
  const comparison=page.locator('#comparison-chart');
  const trend=await comparison.locator('.trend-summary').textContent();
  assert.ok([0,2].every(i=>trend.includes(pct(+data['13'].series[i][3]))),trend);
  console.log('COMPARISON',trend);
  await controls.selectOption('all');
  assert.match(await cards.first().locator('.period-metric').textContent(),/Kapsam geçişi/);
  assert.match(await cards.nth(2).locator('.period-deposit-split').textContent(),/Kapsam geçişi/);
  console.log('FULL HISTORY: difference suppressed across the documented break');
 }finally{await browser.close();}
})().catch(err=>{console.error(err);process.exitCode=1;});
