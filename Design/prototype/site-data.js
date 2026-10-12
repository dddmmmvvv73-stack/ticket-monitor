// Официальные сайты проектов — даты с афиши сайта (прототип вкладки «Аналитика → Сайт», решение пользователя 12.10.2026).
// Ключ — проект (projKey). Строки — что разобрано со страницы: дата, город, площадка, «цена от», ссылка «купить билет».
// Рондо — реальная страница rondotour.ru (12.10.2026, 24 даты). В рабочей системе файл соберёт сборщик (разбор — GigaChat).
// MSITE_GEO — города вне списка рынка с сайтов: [x, y, широта, долгота] (координаты — OpenStreetMap, x/y — проекция market-geo.js).
var MSITE = {
 "александр иванов рондо": {
  "url": "https://rondotour.ru/",
  "checked": "2026-10-12T15:40:00+03:00",
  "rows": [
   {
    "date": "2026-10-18",
    "city": "Подольск",
    "venue": "ДК Октябрь",
    "pmin": 4000,
    "buy": "https://rondotour.ru/podolsk/18-10-26"
   },
   {
    "date": "2026-10-24",
    "city": "Омск",
    "venue": "Концертный зал Филармонии",
    "pmin": 2000,
    "buy": "https://iframeab-pre8991.intickets.ru/seance/72698700"
   },
   {
    "date": "2026-10-26",
    "city": "Кемерово",
    "venue": "Филармония Кузбасса им. Б. Т. Штоколова",
    "pmin": 1800,
    "buy": "https://www.kemfil.ru/afisha/concert?id=5350"
   },
   {
    "date": "2026-10-27",
    "city": "Томск",
    "venue": "БКЗ Томской филармонии",
    "pmin": 2000,
    "buy": "https://tomskfil.ru/afisha/aleksandr-ivanov-i-gruppa-rondo/"
   },
   {
    "date": "2026-11-01",
    "city": "Ессентуки",
    "venue": "КЗ им. Ф.И. Шаляпина",
    "pmin": 1800,
    "buy": "https://essentuki.kassy.ru/events/koncerty-i-shou/6-879/"
   },
   {
    "date": "2026-11-02",
    "city": "Ставрополь",
    "venue": "Ставропольский дворец детского творчества",
    "pmin": 1800,
    "buy": "https://rondotour.ru/stavropol-02-11-26"
   },
   {
    "date": "2026-11-03",
    "city": "Краснодар",
    "venue": "ЦКЗ",
    "pmin": 2500,
    "buy": "https://iframeab-pre8991.intickets.ru/seance/72133324"
   },
   {
    "date": "2026-11-05",
    "city": "Ростов-На-Дону",
    "venue": "Ростовский академический театр драмы им. М. Горького",
    "pmin": 2000,
    "buy": "https://iframeab-pre8991.intickets.ru/seance/71906835"
   },
   {
    "date": "2026-11-07",
    "city": "Липецк",
    "venue": "ОЦКНТ",
    "pmin": 2000,
    "buy": "https://iframeab-pre8991.intickets.ru/seance/71867732"
   },
   {
    "date": "2026-11-08",
    "city": "Воронеж",
    "venue": "МТС LIVE HALL",
    "pmin": 2300,
    "buy": "https://iframeab-pre8991.intickets.ru/seance/72196135"
   },
   {
    "date": "2026-11-09",
    "city": "Тула",
    "venue": "Тульский городской концертный зал",
    "pmin": 2500,
    "buy": "https://iframeab-pre6701.intickets.ru/seance/75649345/"
   },
   {
    "date": "2026-11-12",
    "city": "Череповец",
    "venue": "Дворец металлургов",
    "pmin": 1800,
    "buy": "https://iframeab-pre8991.intickets.ru/seance/72601022"
   },
   {
    "date": "2026-11-14",
    "city": "Люберцы",
    "venue": "Люберецкий дК",
    "pmin": 2500,
    "buy": "https://rondotour.ru/lubertsy/14-11-26"
   },
   {
    "date": "2026-11-15",
    "city": "Зеленоград",
    "venue": "КЦ Зеленоград",
    "pmin": 2500,
    "buy": "https://rondotour.ru/zelenograd/15-11-26"
   },
   {
    "date": "2026-11-18",
    "city": "Курган",
    "venue": "Курганская областная филармония",
    "pmin": 1800,
    "buy": "https://rondotour.ru/kurgan-18-11-26"
   },
   {
    "date": "2026-11-19",
    "city": "Тюмень",
    "venue": "ДК нефтяник",
    "pmin": 2000,
    "buy": "https://iframeab-pre8294.intickets.ru/seance/71869390"
   },
   {
    "date": "2026-11-20",
    "city": "Нижневартовск",
    "venue": "Дворец искусств",
    "pmin": 2000,
    "buy": "https://iframeab-pre8294.intickets.ru/seance/71872577"
   },
   {
    "date": "2026-11-22",
    "city": "Сургут",
    "venue": "Филармония",
    "pmin": 2000,
    "buy": "https://iframeab-pre8991.intickets.ru/seance/71871684"
   },
   {
    "date": "2026-11-29",
    "city": "Серпухов",
    "venue": "ДК Россия",
    "pmin": 2500,
    "buy": "https://rondotour.ru/serpukhov/29-11-2026"
   },
   {
    "date": "2027-01-07",
    "city": "Москва",
    "venue": "КЦ Меридиан",
    "pmin": 2500,
    "buy": "https://rondotour.ru/msk/07-01-27"
   },
   {
    "date": "2027-02-20",
    "city": "Красногорск",
    "venue": "Дк подмосковье",
    "pmin": 2500,
    "buy": "https://rondotour.ru/krasnogorsk/20-02-27"
   },
   {
    "date": "2027-02-21",
    "city": "Раменское",
    "venue": "Дк сатурн",
    "pmin": 2500,
    "buy": "https://rondotour.ru/ramenskoe/21-02-27"
   },
   {
    "date": "2027-02-22",
    "city": "Коломна",
    "venue": "Дк коломна",
    "pmin": 2500,
    "buy": "https://rondotour.ru/kolomna/22-02-27"
   },
   {
    "date": "2027-02-23",
    "city": "Мытищи",
    "venue": "Дк яуза",
    "pmin": 2500,
    "buy": "https://rondotour.ru/mytishchi/23-02-27"
   }
  ]
 }
};
var MSITE_GEO = {"Ессентуки":[-278,162.3,44.0444,42.8606],"Москва":[-260.9,-48.8,55.7558,37.6173]};
