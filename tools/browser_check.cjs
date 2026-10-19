// Reproducible UI walkthrough and real browser recording. No paid requests.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root=path.resolve(__dirname,'..');
  const artifacts=path.join(root,'docs','demo');
  fs.mkdirSync(artifacts,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:process.env.STUDIO_BROWSER_PATH || undefined});
  const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1,recordVideo:{dir:path.join(root,'.tmp','videos'),size:{width:1440,height:1000}},acceptDownloads:true});
  const page=await context.newPage();
  const errors=[],failures=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('requestfailed',r=>failures.push({url:r.url(),error:r.failure()?.errorText}));
  const pause=()=>page.waitForTimeout(1200); // Reading time in the submitted recording.
  try {
    await page.goto(process.env.STUDIO_URL || 'http://127.0.0.1:8765');
    await page.getByRole('heading',{name:'От таблицы к предложению'}).waitFor();
    await page.screenshot({path:path.join(artifacts,'01-start.png'),fullPage:true});
    await pause();
    await page.getByRole('button',{name:'Попробовать на примере'}).click();
    await page.getByText('Таблица проверена. Можно создавать предложения.',{exact:true}).waitFor();
    assert.equal(await page.locator('#clients tr').count(),3);
    await page.screenshot({path:path.join(artifacts,'02-clients.png'),fullPage:true});
    await pause();
    await page.getByRole('button',{name:'Создать предложения',exact:true}).click();
    await page.getByText('Готово. Создано документов: 3.',{exact:true}).waitFor();
    assert.equal(await page.getByRole('link',{name:'Скачать PDF',exact:true}).count(),3);
    await page.screenshot({path:path.join(artifacts,'03-results.png'),fullPage:true});
    await pause();
    const pdfDownload=page.waitForEvent('download');
    await page.getByRole('link',{name:'Скачать PDF',exact:true}).first().click();
    await (await pdfDownload).saveAs(path.join(artifacts,'Демонстрационное предложение.pdf'));
    const journalDownload=page.waitForEvent('download');
    await page.getByRole('link',{name:'Скачать журнал обработки',exact:true}).click();
    await (await journalDownload).saveAs(path.join(root,'.tmp','downloaded-journal.jsonl'));
    // Upload a real Excel file through the file input, then a mixed valid/invalid CSV.
    await page.locator('#file').setInputFiles(path.join(root,'examples','clients.xlsx'));
    await page.getByText('Таблица проверена. Можно создавать предложения.',{exact:true}).waitFor();
    assert.equal(await page.locator('#clients tr').count(),3);
    await pause();
    const invalid='Название компании;Контактное лицо;Потребности клиента;Бюджет\nДемо компания;Анна;Бот для заявок;20000\nОшибка бюджета;Пётр;Сайт;не число\n';
    await page.locator('#file').setInputFiles({name:'Проверка строк.csv',mimeType:'text/csv',buffer:Buffer.from(invalid)});
    await page.getByText(/Таблица проверена. Ошибок: 1/).waitFor();
    await page.screenshot({path:path.join(artifacts,'04-validation.png'),fullPage:true});
    await pause();
    await page.getByRole('button',{name:'Создать предложения',exact:true}).click();
    await page.getByText('Создано документов: 1. Не обработано: 1. Проверьте ошибки ниже.',{exact:true}).waitFor();
    await page.screenshot({path:path.join(artifacts,'05-partial.png'),fullPage:true});
    // Restore the successful example before recording the narrow viewport.
    await page.getByRole('button',{name:'Попробовать на примере'}).click();
    await page.getByText('Таблица проверена. Можно создавать предложения.',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Создать предложения',exact:true}).click();
    await page.getByText('Готово. Создано документов: 3.',{exact:true}).waitFor();
    await pause();
    const mobile=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1});
    const narrow=await mobile.newPage();
    await narrow.goto(process.env.STUDIO_URL || 'http://127.0.0.1:8765');
    await narrow.getByRole('heading',{name:'От таблицы к предложению'}).waitFor();
    await narrow.getByRole('button',{name:'Попробовать на примере'}).click();
    await narrow.getByText('Таблица проверена. Можно создавать предложения.',{exact:true}).waitFor();
    const overflow=await narrow.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
    assert.equal(overflow,false,'Page must not overflow horizontally');
    await narrow.screenshot({path:path.join(artifacts,'06-mobile.png'),fullPage:true});
    await mobile.close();
    assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
    fs.writeFileSync(path.join(artifacts,'browser-check.json'),JSON.stringify({passed:true,checks:['example CSV','XLSX upload','PDF creation','PDF download','journal download','invalid row','partial success','390px viewport'],consoleErrors:errors,requestFailures:failures},null,2));
    console.log('Browser walkthrough passed; screenshot and recording files saved.');
  } finally {
    const video=page.video();
    await context.close();
    if(video)await video.saveAs(path.join(artifacts,'Демонстрация.webm'));
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
