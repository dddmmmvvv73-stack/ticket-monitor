"""Рабочая смета .xlsx: редактируемые входы, формулы, кэш исходных результатов. Ничего не записывает в планирование."""
from __future__ import annotations

import io
import math
import re

from flask import Blueprint, jsonify, request, send_file
from competitors.planning import ORG

bp = Blueprint("tour_export", __name__)
MODES = ("Вал", "Средняя цена", "Распоясовка")
GROUPS = (("variable", "Переменные"), ("project", "Проектные"), ("org", "Организационные"),
          ("rent", "Аренда"), ("logistics", "Логистика"), ("ads", "Реклама"))
ORG_NAMES = ("Машины по городу / трансфер", "Проживание", "Тех.райдер", "Закуп / кейтеринг на площадке",
             "Реквизит / Декорации", "Грузчики", "Охрана", "Службы", "Гладильщица", "Сканировка", "Администратор", "Прочие расходы")


def number(v, hi=1e18):
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= hi:
        raise ValueError("Некорректное число в смете")
    return float(v)


def text(v, limit=1000):
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > limit:
        raise ValueError("Некорректный текст в смете")
    return v


def items(v):
    if not isinstance(v, list) or len(v) > 40:
        raise ValueError("В группе может быть до 40 своих статей")
    result = []
    for a in v:
        if not isinstance(a, dict):
            raise ValueError("Некорректная статья")
        result.append({"name": text(a.get("name"), 120), "amount": number(a.get("amount"))})
    return result


def validate_snapshot(s):
    if not isinstance(s, dict) or s.get("version") != 1:
        raise ValueError("Неизвестный формат сметы")
    rows = s.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 300:
        raise ValueError("Для экспорта нужно от 1 до 300 строк")
    cfg = s.get("cfg")
    if not isinstance(cfg, dict):
        raise ValueError("Нет параметров расчёта")
    classes = cfg.get("classes")
    if not isinstance(classes, list) or not 1 <= len(classes) <= 10:
        raise ValueError("Нет классов прибыли")
    clean_classes = []
    for a in classes:
        if not isinstance(a, list) or len(a) != 2:
            raise ValueError("Некорректный класс прибыли")
        clean_classes.append([text(a[0], 20), number(a[1])])
    out = {k: text(s.get(k), 300) for k in ("title", "project", "month", "created", "scenario")}
    out["cfg"] = {"tax": number(cfg.get("tax"), 100), "target": number(cfg.get("target")), "classes": clean_classes}
    options = s.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("Некорректные параметры экспорта")
    out["options"] = {"zones": options.get("zones") is True}
    out["rows"] = []
    seen = set()
    for r in rows:
        if not isinstance(r, dict) or not re.fullmatch(r"[a-z0-9]{1,24}", str(r.get("id", ""))) or r["id"] in seen:
            raise ValueError("Некорректная строка тура")
        seen.add(r["id"])
        row = {k: text(r.get(k), 1000 if k == "note" else 300) for k in ("id", "city", "venue", "date", "note", "decision")}
        row["mode"] = r.get("mode")
        if row["mode"] not in MODES:
            raise ValueError("Некорректный режим расчёта")
        x = r.get("input")
        if not isinstance(x, dict):
            raise ValueError("Нет входных данных строки")
        fields = "gross seats fill fee cashless per_diem crew days author rao moscow cities rent venue_services logistics ads agent kassa target"
        y = {k: number(x.get(k), 100 if k in ("fill", "cashless", "rao", "agent", "kassa") else 1e18) for k in fields.split()}
        if x.get("target") is None:
            y["target"] = out["cfg"]["target"]
        y["cities"] = max(1, y["cities"])
        y["rao_on"] = x.get("rao_on") is True
        y["per_diem_sum"] = number(x["per_diem_sum"]) if x.get("per_diem_sum") not in (None, "") else None
        org = x.get("org", {})
        if not isinstance(org, dict):
            raise ValueError("Некорректные организационные расходы")
        y["org"] = {k: number(org.get(k)) for k in ORG}
        groups = x.get("cost_items", {})
        if not isinstance(groups, dict):
            raise ValueError("Некорректные свои статьи")
        y["cost_items"] = {g: items(groups.get(g, [])) for g, _ in GROUPS if g != "ads"}
        if any(a["amount"] > 100 for a in y["cost_items"]["variable"]):
            raise ValueError("Ставка своей статьи должна быть от 0 до 100 %")
        y["ad_items"] = items(x.get("ad_items", []))
        zones = x.get("zones", [])
        if not isinstance(zones, list) or len(zones) > 40:
            raise ValueError("До 40 поясов на город")
        y["zones"] = []
        for z in zones:
            if not isinstance(z, dict):
                raise ValueError("Некорректный пояс")
            y["zones"].append({"name": text(z.get("name"), 60), "price": number(z.get("price")), "seats": number(z.get("seats")),
                               "fill": None if z.get("fill") in (None, "") else number(z["fill"], 100)})
        row["input"] = y
        out["rows"].append(row)
    return out


def build_workbook(snapshot):
    import xlsxwriter
    from xlsxwriter.utility import xl_rowcol_to_cell

    s = validate_snapshot(snapshot)
    stream = io.BytesIO()
    wb = xlsxwriter.Workbook(stream, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    wb.set_properties({"title": "Смета — " + s["title"], "author": "Всё схвачено"})
    wb.set_calc_mode("auto")
    summary = wb.add_worksheet("Сводка")
    detail = wb.add_worksheet("Подробные сметы")
    base = {"font_name": "Arial", "font_size": 10, "valign": "vcenter"}
    money = '#,##0.00;[Red]-#,##0.00;–'
    fmt = {"text": wb.add_format(base), "money": wb.add_format(dict(base, num_format=money)),
           "pct": wb.add_format(dict(base, num_format='0.0%')), "int": wb.add_format(dict(base, num_format='#,##0')),
           "title": wb.add_format(dict(base, bold=True, font_size=18)),
           "head": wb.add_format(dict(base, bold=True, bg_color="#F0F4F7", text_wrap=True)),
           "group": wb.add_format(dict(base, bold=True, bg_color="#F0F4F7", num_format=money)),
           "hint": wb.add_format(dict(base, font_color="#716C68", text_wrap=True)),
           "input": wb.add_format(dict(base, font_color="#1265AD", bg_color="#EAF4FF", num_format='0.####')),
           "input_text": wb.add_format(dict(base, font_color="#1265AD", bg_color="#EAF4FF")),
           "link": wb.add_format(dict(base, font_color="#1265AD", underline=True)),
           "negative": wb.add_format({"font_color": "#BC2315"})}
    values = {}

    def put(ws, row, col, value, style="text", formula=None):
        address = xl_rowcol_to_cell(row, col)
        key = (ws.name, address)
        if formula is not None:
            ws.write_formula(row, col, "=" + formula, fmt[style], "" if value is None else value)
        elif value is None:
            ws.write_blank(row, col, None, fmt[style])
        elif isinstance(value, (int, float)):
            ws.write_number(row, col, value, fmt[style])
        else:
            ws.write_string(row, col, value, fmt[style])
        values[key] = value
        return address

    def val(ref):
        return values[(detail.name, ref)] or 0

    def total(row, refs):
        return put(detail, row, 3, sum(val(r) for r in refs), "group", "+".join(refs) or "0")

    summary.set_column("A:A", 22); summary.set_column("B:B", 35); summary.set_column("C:C", 14)
    summary.set_column("D:W", 17); summary.set_column("X:X", 23); summary.set_column("Y:Y", 35)
    summary.merge_range("A1:Y1", "Смета — " + s["title"], fmt["title"])
    summary.merge_range("A2:Y2", s["project"] + " · " + s["month"] + " · " + s["scenario"] + " · " + s["created"], fmt["hint"])
    summary.merge_range("A3:Y3", "Синие ячейки на листе «Подробные сметы» — ввод. Сводка, прибыль и ТБУ пересчитываются автоматически.", fmt["hint"])
    put(summary, 3, 0, "Строк в полном туре")
    denominator = put(summary, 3, 1, s["rows"][0]["input"]["cities"], "input")
    summary.data_validation(3, 1, 3, 1, {"validate": "integer", "criteria": ">=", "value": 1})
    summary.merge_range("C4:Y4", "Делитель московских расходов сохранён по полному туру, даже при экспорте части строк. Его можно изменить.", fmt["hint"])
    summary.merge_range("A5:Y5", "Изменения Excel остаются в файле. Дополнительные статьи: свободные синие строки в каждой группе; детали сворачиваются кнопками слева.", fmt["hint"])
    headers = ["Город", "Площадка", "Дата", "Мест", "Средняя цена, ₽", "Аншлаг, %", "Вал, ₽", "Сборы, ₽", "Переменные, ₽", "Проектные, ₽",
               "Организационные, ₽", "Аренда и службы, ₽", "Логистика, ₽", "Реклама, ₽", "Расходы, ₽", "Прибыль, ₽", "Рентабельность, %",
               "ТБУ продаж, ₽", "ТБУ, билетов", "ТБУ, % аншлага", "Цель прибыли, ₽", "Продать для цели, бил.", "Класс", "Решение", "Заметка"]
    summary.write_row(6, 0, headers, fmt["head"]); summary.set_row(6, 36)
    summary.freeze_panes(7, 2); summary.autofilter(6, 0, 6 + len(s["rows"]), 24)
    summary.set_landscape(); summary.set_paper(9); summary.fit_to_pages(1, 0); summary.repeat_rows(6)
    detail.set_column("A:A", 44); detail.set_column("B:B", 19); detail.set_column("C:C", 13)
    detail.set_column("D:D", 20); detail.set_column("E:E", 25); detail.set_column("F:F", 20)
    detail.merge_range("A1:F1", "Подробные сметы — " + s["title"], fmt["title"])
    detail.merge_range("A2:F2", "Синие ячейки — ввод. Проценты вводите как 10 для 10 %. Пустая заполняемость пояса использует общую. Режим расчёта переключается списком.", fmt["hint"])
    detail.set_row(1, 34); detail.freeze_panes(2, 1)
    detail.outline_settings(True, False, True, False)
    detail.set_landscape(); detail.set_paper(9); detail.fit_to_pages(1, 0)
    refs_by_row = []
    cursor = 3
    breaks = []
    for i, row in enumerate(s["rows"]):
        x, refs = row["input"], {}
        start = cursor; breaks.append(start)
        detail.merge_range(start, 0, start, 5, f'{i+1}. {row["city"]} — {row["venue"]}', fmt["head"])
        cursor += 1

        def inp(key, label, value, unit="", note="", pct=False):
            nonlocal cursor
            rr = cursor; cursor += 1
            put(detail, rr, 0, label)
            refs[key] = put(detail, rr, 1, value, "input_text" if isinstance(value, str) else "input")
            put(detail, rr, 2, unit); put(detail, rr, 4, note, "hint")
            if not isinstance(value, str):
                detail.data_validation(rr, 1, rr, 1, {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 100 if pct else 1e18,
                                                     "error_title": "Проверьте значение", "error_message": "Введите неотрицательное число" + (" от 0 до 100" if pct else ""), "error_type": "stop"})
            return refs[key]

        inp("city", "Город", row["city"]); inp("venue", "Площадка", row["venue"]); inp("date", "Дата", row["date"])
        mode = inp("mode", "Режим расчёта", row["mode"])
        detail.data_validation(cursor-1, 1, cursor-1, 1, {"validate": "list", "source": list(MODES)})
        seats = inp("seats", "Мест в продаже", x["seats"], "бил.", "Для режима вала / средней цены")
        avg = x["gross"] / x["seats"] if x["seats"] else 0
        price = inp("price", "Средняя цена билета", avg, "₽", "Для режима средней цены")
        gross = inp("gross", "Вал площадки", x["gross"], "₽", "Для режима вала")
        fill = inp("fill", "Заполняемость", x["fill"], "%", pct=True)
        target = inp("target", "Цель прибыли", x["target"], "₽")
        zone_head = cursor; cursor += 1
        detail.write_row(zone_head, 0, ["Распоясовка", "Цена, ₽", "Билетов", "Аншлаг, %", "Вал, ₽", "Сборы, ₽"], fmt["head"])
        z_gross, z_sales, z_seats = [], [], []
        for z in x["zones"] + [{"name": "", "price": 0, "seats": 0, "fill": None}] * 3:
            rr = cursor; cursor += 1
            put(detail, rr, 0, z["name"], "input_text")
            zp = put(detail, rr, 1, z["price"], "input")
            zs = put(detail, rr, 2, z["seats"], "input")
            zf = put(detail, rr, 3, z["fill"], "input")
            zg = put(detail, rr, 4, z["price"] * z["seats"], "money", zp + "*" + zs)
            zv = val(zg) * (x["fill"] if z["fill"] is None else z["fill"]) / 100
            z_sales.append(put(detail, rr, 5, zv, "money", f'{zg}*IF({zf}="",{fill},{zf})/100'))
            z_gross.append(zg); z_seats.append(zs)
            detail.data_validation(rr, 1, rr, 2, {"validate": "decimal", "criteria": ">=", "value": 0})
            detail.data_validation(rr, 3, rr, 3, {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 100})
            detail.set_row(rr, None, None, {"level": 1, "hidden": not s["options"]["zones"]})
        detail.set_row(zone_head, None, None, {"collapsed": not s["options"]["zones"]})

        def result(key, label, value, formula, style="money"):
            nonlocal cursor
            rr = cursor; cursor += 1
            put(detail, rr, 0, label)
            refs[key] = put(detail, rr, 3, value, style, formula)
            return refs[key]

        zone_mode = row["mode"] == "Распоясовка"
        active_seats = sum(val(z) for z in z_seats) if zone_mode else x["seats"]
        active_gross = sum(val(z) for z in z_gross) if zone_mode else x["gross"]
        rs = result("actual_seats", "Мест — расчёт", active_seats, f'IF({mode}="Распоясовка",SUM({z_seats[0]}:{z_seats[-1]}),{seats})', "int")
        rg = result("actual_gross", "Вал — расчёт", active_gross, f'IF({mode}="Распоясовка",SUM({z_gross[0]}:{z_gross[-1]}),IF({mode}="Средняя цена",{price}*{seats},{gross}))')
        ra = result("actual_avg", "Средняя цена — расчёт", active_gross/active_seats if active_seats else 0, f'IF({rs}>0,{rg}/{rs},0)')
        active_sales = sum(val(z) for z in z_sales) if zone_mode else active_gross*x["fill"]/100
        sales = result("sales", "Сборы", active_sales, f'IF({mode}="Распоясовка",SUM({z_sales[0]}:{z_sales[-1]}),{rg}*{fill}/100)')
        result("fill_eff", "Заполняемость — расчёт", active_sales/active_gross if active_gross else x["fill"]/100, f'IF({rg}>0,{sales}/{rg},{fill}/100)', "pct")
        group_refs, rate_refs = {}, []
        for key, label in GROUPS:
            group_row = cursor; cursor += 1
            put(detail, group_row, 0, label, "group")
            group_items = []

            def expense(name, amount, rate=False, formula=None, computed=None, note="", refkey=None):
                rr = cursor
                b = inp(refkey or "expense", name, amount, "%" if rate else "₽", note, pct=rate)
                expression = formula(b) if formula else (sales+"*"+b+"/100" if rate else b)
                value = computed if computed is not None else (active_sales*amount/100 if rate else amount)
                d = put(detail, rr, 3, value, "money", expression)
                group_items.append(d)
                if key == "variable" and rate:
                    rate_refs.append(b)
                return d

            if key == "variable":
                on = inp("rao_on", "РАО / ВОИС включено", 1 if x["rao_on"] else 0, "0 / 1")
                detail.data_validation(cursor-1, 1, cursor-1, 1, {"validate": "list", "source": [0, 1]})
                expense("Ставка РАО / ВОИС", x["rao"], True, lambda b: f'{sales}*{b}*{on}/100', active_sales*x["rao"]/100 if x["rao_on"] else 0, refkey="rao")
                rate_refs.pop(); rate_refs.append(f'({refs["rao"]}*{on})')
                expense("Налог", s["cfg"]["tax"], True)
                expense("Комиссия касс", x["kassa"], True)
                expense("Агентские", x["agent"], True)
            elif key == "project":
                fee = expense("Гонорар", x["fee"])
                expense("Безналичная оплата", x["cashless"], True, lambda b: f'{fee}*{b}/100', x["fee"]*x["cashless"]/100, "Процент от гонорара")
                pd = inp("per_diem", "Суточные, ставка", x["per_diem"], "₽ / чел.")
                crew = inp("crew", "Состав", x["crew"], "чел.")
                days = inp("days", "Дней в городе", x["days"], "дн.")
                pd_sum = inp("per_diem_sum", "Суточные всего (необязательно)", x["per_diem_sum"], "₽", "Пусто — ставка × состав × дни")
                rr = cursor; cursor += 1; put(detail, rr, 0, "Суточные — итог")
                group_items.append(put(detail, rr, 3, x["per_diem_sum"] if x["per_diem_sum"] is not None else x["per_diem"]*x["crew"]*x["days"], "money", f'IF({pd_sum}="",{pd}*{crew}*{days},{pd_sum})'))
                expense("Авторские", x["author"])
                expense("Московские расходы на тур", x["moscow"], formula=lambda b: f"{b}/MAX(1,'Сводка'!${denominator[0]}${denominator[1:]})", computed=x["moscow"]/s["rows"][0]["input"]["cities"], note="Делитель — Сводка!B4")
            elif key == "org":
                for org_key, name in zip(ORG, ORG_NAMES):
                    expense(name, x["org"][org_key])
            elif key == "rent":
                expense("Аренда площадки", x["rent"]); expense("Службы площадки", x["venue_services"])
            elif key == "logistics":
                expense("Логистика", x["logistics"])
            else:
                expense("Рекламный бюджет", x["ads"])
            custom = x["ad_items"] if key == "ads" else x["cost_items"][key]
            for index, a in enumerate(custom + [{"name": "", "amount": 0}] * 3):
                rr = cursor
                name = a["name"] or ("Своя статья" if index < len(custom) else "")
                expense(name, a["amount"], key == "variable")
                put(detail, rr, 0, name, "input_text")
            for rr in range(group_row+1, cursor):
                detail.set_row(rr, None, None, {"level": 1})
            group_refs[key] = total(group_row, group_items)
        var = group_refs["variable"]
        var_rate = sum([x["rao"] if x["rao_on"] else 0, s["cfg"]["tax"], x["kassa"], x["agent"]] + [a["amount"] for a in x["cost_items"]["variable"]]) / 100
        vr = result("var_rate", "Переменные, доля от сборов", var_rate, '('+'+'.join(rate_refs)+')/100', "pct")
        fixed_refs = [group_refs[k] for k, _ in GROUPS if k != "variable"]
        fixed = result("fixed", "Постоянные расходы", sum(val(r) for r in fixed_refs), '+'.join(fixed_refs))
        total_ref = result("total", "Итоговые расходы", val(fixed)+val(var), fixed+'+'+var)
        profit = result("profit", "Прибыль", active_sales-val(total_ref), sales+'-'+total_ref)
        result("ros", "Рентабельность продаж", val(profit)/active_sales if active_sales > 0 else None, f'IF({sales}>0,{profit}/{sales},"")', "pct")
        result("roi", "Окупаемость затрат", val(profit)/val(total_ref) if val(total_ref) > 0 else None, f'IF({total_ref}>0,{profit}/{total_ref},"")', "pct")
        result("eff", "Эффективность слота", val(profit)/active_gross if active_gross > 0 else None, f'IF({rg}>0,{profit}/{rg},"")', "pct")
        net = val(ra)*(1-var_rate)
        be = val(fixed)/net if net > 0 else None
        result("beTickets", "ТБУ, билетов", math.ceil(be) if be is not None else None, f'IF({ra}*(1-{vr})>0,ROUNDUP({fixed}/({ra}*(1-{vr})),0),"")', "int")
        result("beRub", "ТБУ продаж", be*val(ra) if be is not None else None, f'IF({ra}*(1-{vr})>0,{fixed}/(1-{vr}),"")')
        result("beShare", "ТБУ, доля зала", be/active_seats if be is not None and active_seats else None, f'IF(AND({ra}*(1-{vr})>0,{rs}>0),{fixed}/({ra}*(1-{vr}))/{rs},"")', "pct")
        tg = (val(fixed)+x["target"])/net if net > 0 else None
        result("tgTickets", "Продать для цели, билетов", math.ceil(tg) if tg is not None else None, f'IF({ra}*(1-{vr})>0,ROUNDUP(({fixed}+{target})/({ra}*(1-{vr})),0),"")', "int")
        cl_formula, cl_value = '"D"', "D"
        for name, threshold in reversed(s["cfg"]["classes"]):
            cl_formula = f'IF({profit}>={threshold},"{name.replace(chr(34), chr(34)*2)}",{cl_formula})'
            if val(profit) >= threshold:
                cl_value = name
        result("cls", "Класс по прибыли", cl_value, cl_formula, "text")
        inp("decision", "Решение", row["decision"]); inp("note", "Заметка", row["note"])
        refs.update(group_refs)
        refs_by_row.append(refs)
        detail.conditional_format(start, 3, cursor-1, 3, {"type": "cell", "criteria": "<", "value": 0, "format": fmt["negative"]})
        cursor += 3
    detail.set_h_pagebreaks(breaks[1:1024])
    detail.print_area(0, 0, cursor-1, 5)
    columns = ["city", "venue", "date", "actual_seats", "actual_avg", "fill_eff", "actual_gross", "sales", "variable", "project", "org", "rent", "logistics", "ads",
               "total", "profit", "ros", "beRub", "beTickets", "beShare", "target", "tgTickets", "cls", "decision", "note"]
    for i, refs in enumerate(refs_by_row):
        for col, key in enumerate(columns):
            ref = refs[key]; value = values[(detail.name, ref)]
            style = "text" if col in (0, 1, 2, 22, 23, 24) else "pct" if col in (5, 16, 19) else "int" if col in (3, 18, 21) else "money"
            put(summary, i+7, col, value, style, f"'Подробные сметы'!{ref}")
        summary.write_url(i+7, 0, f"internal:'Подробные сметы'!A{breaks[i]+1}", fmt["link"], s["rows"][i]["city"])
    end = 7+len(refs_by_row)
    put(summary, end, 0, "Итого", "group")
    for col in range(3, 22):
        if col not in (3, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15):
            continue
        letters = xl_rowcol_to_cell(0, col)[:-1]
        cache = sum(values[(summary.name, xl_rowcol_to_cell(i+7, col))] or 0 for i in range(len(refs_by_row)))
        put(summary, end, col, cache, "group", f'SUM({letters}8:{letters}{end})')
    summary.conditional_format(7, 15, end, 15, {"type": "cell", "criteria": "<", "value": 0, "format": fmt["negative"]})
    summary.print_area(0, 0, end, 22)
    wb.close()
    return stream.getvalue()


@bp.post("/api/planning/export.xlsx")
def export_xlsx():
    if request.content_length and request.content_length > 8_000_000:
        return jsonify({"error": "Смета больше 8 МБ"}), 413
    body = request.get_json(silent=True)
    try:
        data = build_workbook(body)
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"error": str(exc)}), 400
    except ImportError:
        return jsonify({"error": "На сервере не установлена библиотека экспорта Excel"}), 503
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', ' ', str(body.get("title", "Тур"))).strip()[:100]
    return send_file(io.BytesIO(data), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name="Смета — " + title + ".xlsx")
