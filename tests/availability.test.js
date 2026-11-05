const {test}=require('node:test');
const assert=require('node:assert/strict');
const {parseDays,monthShift,makeIndex,resolve}=require('../Design/prototype/availability.js');
test('даты месяца: диапазоны, високосный февраль, неверный ввод',()=>{
  assert.deepEqual(parseDays('5, 8; 12–15, 8','2027-02'),[5,8,12,13,14,15]);
  assert.deepEqual(parseDays('29','2028-02'),[29]);
  for(const text of ['29','32','5-2','1, слово','0'])assert.throws(()=>parseDays(text,'2027-02'));
  assert.equal(monthShift('2026-12',2),'2027-02');
});
const report=(p={})=>({venue:'v1',month:'2027-02',mode:'full',asof:'2026-11-05',created:'2026-11-05T09:00:00',free:[5,8],busy:[],...p});
test('полный и частичный ответы: не теряем нетронутые даты и не называем неизвестное занятым',()=>{
  let db={reports:{a:report({mode:'partial'})}};
  assert.equal(resolve(makeIndex(db),'v1','2027-02-06','2026-11-05').status,'unknown');
  db.reports={a:report(),b:report({mode:'partial',created:'2026-11-05T10:00:00',free:[],busy:[5]})};
  const idx=makeIndex(db);
  assert.equal(resolve(idx,'v1','2027-02-05','2026-11-05').status,'busy');
  assert.equal(resolve(idx,'v1','2027-02-08','2026-11-05').status,'free');
  assert.equal(resolve(idx,'v1','2027-02-06','2026-11-05').status,'busy');
  db.reports.b.void=true;
  assert.equal(resolve(makeIndex(db),'v1','2027-02-05','2026-11-05').status,'free');
});
test('резерв перекрывает ответ; срок не освобождает дату; после снятия нужна новая проверка',()=>{
  const b={venue:'v1',date:'2027-02-05',status:'hold',until:'2026-11-04',status_at:'2026-11-05T10:00:00'};
  const db={reports:{a:report()},bookings:{b}};
  let x=resolve(makeIndex(db),'v1',b.date,'2026-11-05');assert.equal(x.status,'hold');assert.equal(x.overdue,true);
  b.status='confirmed';assert.equal(resolve(makeIndex(db),'v1',b.date,'2026-11-05').status,'confirmed');
  b.status='cancelled';assert.equal(resolve(makeIndex(db),'v1',b.date,'2026-11-05').status,'recheck');
  db.reports.c=report({mode:'partial',created:'2026-11-05T11:00:00',free:[5]});
  assert.equal(resolve(makeIndex(db),'v1',b.date,'2026-11-05').status,'free');
});
