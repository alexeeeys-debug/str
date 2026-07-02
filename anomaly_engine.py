"""
Движок поиска ошибок заполнения сумм начислений в реестре.

Направление отклонения:
  +1  значение ВЫШЕ ожидаемого  -> градиент КРАСНОГО
  -1  значение НИЖЕ ожидаемого  -> градиент ЗЕЛЁНОГО
Насыщенность цвета растёт с серьёзностью.

Методы (по приоритету):
  1. Структурная сверка (детерминированная): сумма=Σкв, среднее=сумма/n, Всего=Σкв.
  2. Робастный z-score в лог-пространстве по истории клиента (median + MAD).
  3. Скачок к прошлому периоду (QoQ) и год-к-году (YoY) в разах.
  4. Сравнение с группой-аналогом (Тип × Резидент) — для короткой истории.
"""
import re
import numpy as np

MIN_HISTORY = 6
Z_THRESHOLD = 3.5
RATIO_THRESHOLD = 8
PEER_Z_THRESHOLD = 3.5


def analyze_clients(clients, min_history=MIN_HISTORY, z_thr=Z_THRESHOLD,
                    ratio_thr=RATIO_THRESHOLD, peer_z_thr=PEER_Z_THRESHOLD, quarters=None,
                    trailing_window=3, pct_threshold=10.0, enable_trailing=True):
    flags = {}
    peer = {}
    for c in clients:
        pos = c['series'][(~np.isnan(c['series'])) & (c['series'] > 0)]
        peer.setdefault((c['type'], c['resident']), []).extend(np.log10(pos).tolist())
    peer_stat = {}
    for k, a in peer.items():
        a = np.array(a)
        if len(a) >= min_history:
            m = np.median(a); peer_stat[k] = (m, np.median(np.abs(a - m)))

    def add(cid, ct, rs, q, v, sev, reason, direction, lo=None, hi=None):
        key = (cid, q); f = flags.get(key)
        if f is None:
            flags[key] = dict(client_id=cid, ctype=ct, resident=rs, quarter=q, value=v,
                              severity=sev, direction=direction, reasons=[reason],
                              lo=lo, hi=hi, _top=sev)
        else:
            if sev > f['_top']:
                f['_top'] = sev; f['direction'] = direction
            f['severity'] = max(f['severity'], sev)
            f['reasons'].append(reason)
            if lo is not None:
                f['lo'], f['hi'] = lo, hi

    for c in clients:
        cid, ct, rs, s = str(c['id']), c['type'], c['resident'], c['series']
        pos = s[(~np.isnan(s)) & (s > 0)]
        has_own = len(pos) >= min_history

        if has_own:
            lg = np.log10(pos); med = np.median(lg); mad = np.median(np.abs(lg - med))
            if mad > 0:
                lo = 10 ** (med - z_thr * mad / 0.6745)
                hi = 10 ** (med + z_thr * mad / 0.6745)
                for i, q in enumerate(quarters):
                    v = s[i]
                    if np.isnan(v) or v <= 0:
                        continue
                    z = 0.6745 * (np.log10(v) - med) / mad
                    if abs(z) > z_thr:
                        sev = min(0.95, 0.22 + (abs(z) - z_thr) / 20)
                        add(cid, ct, rs, q, v, sev,
                            f"Робастный z={z:+.1f}: {'выше' if z>0 else 'ниже'} обычного уровня клиента",
                            1 if z > 0 else -1, lo, hi)

        filled = [(i, s[i]) for i in range(len(s)) if not np.isnan(s[i]) and s[i] > 0]
        for k in range(1, len(filled)):
            i, v = filled[k]; pi, pv = filled[k - 1]; r = v / pv
            if r >= ratio_thr or r <= 1 / ratio_thr:
                sev = min(0.98, 0.30 + np.log10(max(r, 1 / r)) / 9)
                add(cid, ct, rs, quarters[i], v, sev,
                    f"Скачок к прошлому периоду ×{r:,.1f} (относительно {quarters[pi]})",
                    1 if r > 1 else -1)
        for i in range(4, len(s)):
            v, pv = s[i], s[i - 4]
            if not np.isnan(v) and not np.isnan(pv) and v > 0 and pv > 0:
                r = v / pv
                if r >= ratio_thr or r <= 1 / ratio_thr:
                    sev = min(0.9, 0.25 + np.log10(max(r, 1 / r)) / 9)
                    add(cid, ct, rs, quarters[i], v, sev,
                        f"Скачок год-к-году ×{r:,.1f} (относительно {quarters[i-4]})",
                        1 if r > 1 else -1)

        # 5) отклонение от МЕДИАНЫ за последние N кварталов (порог в %), опционально
        if enable_trailing:
            for i in range(len(s)):
                v = s[i]
                if np.isnan(v) or v <= 0:
                    continue
                prev = [s[j] for j in range(i - 1, -1, -1) if not np.isnan(s[j]) and s[j] > 0][:trailing_window]
                if not prev:
                    continue
                base = float(np.median(prev))
                if base <= 0:
                    continue
                pct = (v - base) / base * 100.0
                if abs(pct) > pct_threshold:
                    sev = min(0.95, 0.30 + np.log10(1 + abs(pct) / 100.0) / 3.0)
                    add(cid, ct, rs, quarters[i], v, sev,
                        f"Отклонение {pct:+.0f}% от медианы за последние {len(prev)} кв. "
                        f"(медиана={base:,.0f}, порог {pct_threshold:.0f}%)",
                        1 if pct > 0 else -1)

        if not has_own:
            ps = peer_stat.get((ct, rs))
            if ps and ps[1] > 0:
                med, mad = ps
                for i, q in enumerate(quarters):
                    v = s[i]
                    if np.isnan(v) or v <= 0:
                        continue
                    z = 0.6745 * (np.log10(v) - med) / mad
                    if abs(z) > peer_z_thr:
                        sev = min(0.85, 0.22 + (abs(z) - peer_z_thr) / 20)
                        add(cid, ct, rs, q, v, sev,
                            f"Мало истории клиента; отклонение от группы «{ct}/{rs}» (z={z:+.1f})",
                            1 if z > 0 else -1)

    out = list(flags.values())
    out.sort(key=lambda f: f['severity'], reverse=True)
    for f in out:
        f['level'] = 'Высокая' if f['severity'] >= 0.60 else 'Средняя' if f['severity'] >= 0.42 else 'Низкая'
    return out


def gradient_hex(severity, direction):
    """Красный градиент для отклонений вверх (+1), зелёный — вниз (-1)."""
    t = min(1.0, max(0.0, (severity - 0.20) / 0.70))
    if direction > 0:
        c0, c1 = (0xFD, 0xE3, 0xE3), (0xA8, 0x14, 0x14)
    else:
        c0, c1 = (0xE3, 0xF4, 0xE3), (0x14, 0x63, 0x1C)
    rgb = tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
    return '%02X%02X%02X' % rgb, t > 0.55


def load_registry(wb):
    """Авто-детект: строка заголовка с «ID клиента», колонки вида ГГГГQК."""
    ws = wb[wb.sheetnames[0]]
    hdr = None
    for r in range(1, min(ws.max_row, 40) + 1):
        for c in range(1, ws.max_column + 1):
            v = str(ws.cell(r, c).value or '')
            if 'ID' in v and 'клиент' in v.lower():
                hdr = r; break
        if hdr:
            break
    if hdr is None:
        raise ValueError("Не найдена строка заголовка с «ID клиента».")
    col = {}; qcol = {}
    for c in range(1, ws.max_column + 1):
        h = str(ws.cell(hdr, c).value or '').replace('\n', ' ').strip()
        if 'ID' in h and 'клиент' in h.lower(): col['id'] = c
        elif h == 'Тип': col['type'] = c
        elif h == 'Резидент': col['res'] = c
        elif re.fullmatch(r'\d{4}Q[1-4]', h): qcol[h] = c
    quarters = sorted(qcol, key=lambda q: (int(q[:4]), int(q[-1])))
    clients = []; blanks = 0; r = hdr + 1
    while r <= ws.max_row and blanks < 5:
        cid = ws.cell(r, col['id']).value
        if cid in (None, ''):
            blanks += 1; r += 1; continue
        blanks = 0
        series = np.array([
            (lambda v: np.nan if v in (None, '') else float(v))(ws.cell(r, qcol[q]).value)
            for q in quarters])
        clients.append(dict(id=cid, type=ws.cell(r, col.get('type', 0)).value,
                            resident=ws.cell(r, col.get('res', 0)).value,
                            series=series, row=r))
        r += 1
    return ws, hdr, col, qcol, quarters, clients
