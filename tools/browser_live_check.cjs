// One real AI request on a synthetic company, with an honest success/failure capture.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const root=path.resolve(__dirname,'..');
  const browser=await chromium.launch({headless:true,executablePath:process.env.STUDIO_BROWSER_PATH||undefined});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  try{
    await page.goto(process.env.STUDIO_URL||'http://127.0.0.1:8765');
    const csv=fs.readFileSync(path.join(root,'examples','clients.csv'),'utf8').trim().split(/\r?\n/).slice(0,2).join('\n')+'\n';
    await page.locator('#file').setInputFiles({name:'Один тестовый клиент.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
    await page.getByText('Таблица проверена. Можно создавать предложения.',{exact:true}).waitFor();
    await page.getByRole('radio',{name:'С помощью AI Расходует баланс ProxyAPI'}).check();
    await page.getByRole('button',{name:'Создать предложения',exact:true}).click();
    await page.locator('#results-section').waitFor({state:'visible',timeout:120000});
    const status=await page.locator('#message').innerText();
    const details=await page.locator('#results').innerText();
    await page.screenshot({path:path.join(root,'docs','demo','07-live-api.png'),fullPage:true});
    fs.writeFileSync(path.join(root,'docs','demo','live-check.json'),JSON.stringify({status,details,success:status.startsWith('Готово.')},null,2));
    console.log(status,details);
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
