"""
Контроль ошибок заполнения сумм начислений — Streamlit.

Запуск:
    pip install -r requirements.txt
    streamlit run app.py

Красный градиент = значение ВЫШЕ ожидаемого, зелёный = НИЖЕ. Насыщенность растёт
с серьёзностью. Разметку столбцов приложение определяет само.
"""
import io
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
import openpyxl
from openpyxl.styles import PatternFill, Font
from openpyxl.comments import Comment
from anomaly_engine import analyze_clients, load_registry, gradient_hex

st.set_page_config(page_title="Контроль начислений", layout="wide")


def build_annotated(wb, ws, qcol, clients, flags):
    row_of = {str(c['id']): c['row'] for c in clients}
    for f in flags:
        cell = ws.cell(row_of[f['client_id']], qcol[f['quarter']])
        hexc, dark = gradient_hex(f['severity'], f['direction'])
        cell.fill = PatternFill('solid', fgColor=hexc)
        if dark:
            cell.font = Font(name=cell.font.name or 'Arial', color='FFFFFF', bold=True)
        exp = f"\nОбычный диапазон: {f['lo']:,.0f} … {f['hi']:,.0f}" if f.get('lo') else ''
        arrow = 'ВЫШЕ ожидаемого ↑' if f['direction'] > 0 else 'НИЖЕ ожидаемого ↓'
        cm = Comment(f"⚠ {arrow} | {f['level']}\nЗначение: {f['value']:,.2f}\n\n" +
                     "\n".join('• ' + r for r in f['reasons']) + exp, "Контроль")
        cm.width = 320; cm.height = 240; cell.comment = cm
    bio = io.BytesIO(); wb.save(bio); return bio.getvalue()


def main():
    st.title("Контроль ошибок заполнения сумм начислений")
    st.caption("Красный — сумма ВЫШЕ ожидаемого, зелёный — НИЖЕ. Насыщенность растёт с серьёзностью. "
               "Сравнение: история клиента (робастная лог-статистика), прошлый период, группа-аналог.")

    with st.sidebar:
        st.header("Чувствительность")
        # Кнопка со всплывающей инструкцией
        with st.popover("ℹ️ Инструкция по настройкам"):
            st.markdown("""
                    **Основные статистические параметры:**
                    * **Порог робастного z-score:** Насколько сильно текущее значение выбивается из исторического коридора клиента. Оно показывает, во сколько раз текущее отклонение превышает типичный для этого клиента разброс. 3.5 считается оптимальной границей. Этот порог пропускает обычный бизнес-шум и небольшие колебания, но четко ловит явные странности. Чем *ниже* порог, тем *выше* чувствительность.
                    * **Порог скачка (в разах):** Прямолинейный фильтр для поиска грубых ошибок масштаба (например, лишний ноль или сдвиг запятой).
                    * **Мин. история клиента (кварталы):** Ограничение по объему данных, необходимых для достоверного анализа. Если истории меньше, не будет применяться метод модифицированного (робастного) z-score.

                    **Проверка по медиане последних кварталов:**
                    * Полезна для поиска локальных аномалий, если тренд клиента недавно изменился.
                    * **Окно:** За сколько последних кварталов считать медиану (эталон).
                    * **Порог отклонения:** Допустимый процент колебаний относительно этого недавнего эталона. Ниже порог → больше срабатываний.
                    """)
        z_thr = st.slider("Порог робастного z-score", 2.5, 6.0, 3.5, 0.5)
        ratio_thr = st.slider("Порог скачка (в разах)", 3, 20, 8, 1)
        min_history = st.slider("Мин. история клиента (кварталы)", 3, 12, 6, 1)
        st.divider()
        enable_trailing = st.checkbox("Проверка по медиане последних кварталов", value=True)
        trailing_window = st.number_input("Окно (последних кварталов)",
                                          min_value=1, max_value=12, value=4, step=1,
                                          disabled=not enable_trailing)
        pct_threshold = st.number_input("Порог отклонения от медианы, %",
                                        min_value=1.0, max_value=500.0, value=50.0, step=5.0,
                                        disabled=not enable_trailing)
        st.caption("Ниже порог → больше срабатываний.")

    up = st.file_uploader("Файл реестра (.xlsx)", type=['xlsx'])
    if not up:
        st.info("Ожидается загрузка файла.")
        st.stop()

    wb = openpyxl.load_workbook(up)
    ws, hdr, col, qcol, quarters, clients = load_registry(wb)
    with st.spinner(f"Анализ {len(clients)} клиентов…"):
        flags = analyze_clients(clients, min_history, z_thr, ratio_thr, z_thr, quarters,
                                trailing_window=int(trailing_window), pct_threshold=float(pct_threshold),
                                enable_trailing=bool(enable_trailing))

    st.divider()

    # --- НОВЫЙ БЛОК: Выбор периода для отображения на экране ---
    period_options = ["Все периоды"] + list(quarters)[::-1]
    selected_period = st.selectbox("📅 Выберите период для вывода отчета на экран:", period_options)

    # Фильтруем аномалии по выбранному периоду
    if selected_period == "Все периоды":
        display_flags = flags
    else:
        display_flags = [f for f in flags if f['quarter'] == selected_period]
    # -----------------------------------------------------------

    n_up = sum(f['direction'] > 0 for f in display_flags)
    n_dn = sum(f['direction'] < 0 for f in display_flags)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Клиентов (всего)", len(clients))
    c2.metric("Подозрительных значений", len(display_flags))
    c3.metric("Вверх (красный)", n_up)
    c4.metric("Вниз (зелёный)", n_dn)

    st.subheader(f"Ранжированный список ({selected_period})")
    rows = []
    for f in display_flags:
        rows.append({'ID клиента': f['client_id'], 'Тип': f['ctype'], 'Резидент': f['resident'],
                     'Период': f['quarter'], 'Значение': round(f['value'], 2),
                     'Напр.': '↑ выше' if f['direction'] > 0 else '↓ ниже',
                     'Ожид. диапазон': (f"{f['lo']:,.0f} … {f['hi']:,.0f}" if f.get('lo') else '—'),
                     'Серьёзность': f['level'], '_sev': f['severity'], '_dir': f['direction'],
                     'Причина(ы)': '; '.join(f['reasons'])})
    df = pd.DataFrame(rows)

    # Проверка на пустой датафрейм, чтобы избежать ошибок при отрисовке стилей
    if df.empty:
        st.success(f"🎉 В периоде «{selected_period}» подозрительных начислений не найдено!")
    else:
        def row_style(row):
            hexc, dark = gradient_hex(row['_sev'], row['_dir'])
            style = f'background-color:#{hexc}' + (';color:white' if dark else '')
            return [style if col in ('Значение', 'Напр.') else '' for col in df.columns]

        st.dataframe(df.style.apply(row_style, axis=1).hide(['_sev', '_dir'], axis=1),
                     use_container_width=True, height=430)

    st.divider()

    dl_col1, dl_col2 = st.columns(2)

    with dl_col1:
        # Первая кнопка: скачивает файл со всеми найденными аномалиями
        st.download_button(
            label="⬇ Скачать размеченный Excel (все периоды)",
            data=build_annotated(wb, ws, qcol, clients, flags),
            file_name="реестр_начислений_все.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    with dl_col2:
        # Для второй кнопки загружаем "чистый" файл заново,
        # чтобы стили от первой кнопки не смешались с этой
        wb_filtered = openpyxl.load_workbook(up)
        ws_filtered = wb_filtered[ws.title]

        # Вторая кнопка: скачивает разметку только для выбранного периода
        st.download_button(
            label=f"⬇ Скачать Excel (только {selected_period})",
            data=build_annotated(wb_filtered, ws_filtered, qcol, clients, display_flags),
            file_name=f"реестр_начислений_{selected_period}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=(selected_period == "Все периоды")  # Делаем кнопку неактивной, если выбран фильтр "Все периоды"
        )

    st.subheader("Профиль клиента")
    ids = [str(c['id']) for c in clients]

    # Логика выбора клиента по умолчанию: берем первого из отфильтрованных,
    # а если список пуст - берем просто первого нарушителя из всех периодов
    if display_flags:
        default_ix = ids.index(display_flags[0]['client_id'])
    elif flags:
        default_ix = ids.index(flags[0]['client_id'])
    else:
        default_ix = 0

    sel = st.selectbox("Клиент", ids, index=default_ix)
    c = next(c for c in clients if str(c['id']) == sel)
    fmap = {f['quarter']: f['direction'] for f in flags if f['client_id'] == sel}
    cd = pd.DataFrame({'Период': quarters, 'Сумма': c['series'],
                       'Статус': ['выше ↑' if fmap.get(q, 0) > 0 else 'ниже ↓' if fmap.get(q, 0) < 0 else 'норма'
                                  for q in quarters]}).dropna(subset=['Сумма'])
    base = alt.Chart(cd).encode(x=alt.X('Период:N', sort=quarters))
    line = base.mark_line(color='#95A5A6').encode(y=alt.Y('Сумма:Q', scale=alt.Scale(type='log')))
    pts = base.mark_circle(size=95).encode(
        y='Сумма:Q',
        color=alt.Color('Статус:N', scale=alt.Scale(
            domain=['норма', 'выше ↑', 'ниже ↓'], range=['#3498DB', '#C0392B', '#1E8449'])),
        tooltip=['Период', 'Сумма', 'Статус'])
    st.altair_chart((line + pts).properties(height=340), use_container_width=True)
    st.caption("Ось Y — логарифмическая: ошибки «лишний ноль / сдвиг запятой» видны как резкие ступени.")


if __name__ == '__main__':
    main()
