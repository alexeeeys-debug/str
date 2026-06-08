import streamlit as st
import pandas as pd
import math
import datetime
import plotly.graph_objects as go

# --- Настройка страницы ---
st.set_page_config(page_title="Mortgage Strategy Pro", layout="wide")


# --- Вспомогательные функции ---
def fmt_money(n):
    if pd.isna(n) or n is None:
        return ""
    return f"{n:,.0f} ₽".replace(",", " ")


def format_term(months):
    if pd.isna(months) or months is None:
        return ""
    y = months // 12
    m = months % 12
    return f"{y}г {m}м"


def add_months(d, months):
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31,
                     30, 31, 30, 31]
    day = min(d.day, days_in_month[month - 1])
    return datetime.date(year, month, day)


def get_ru_date(d):
    months_ru = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября',
                 'ноября', 'декабря']
    return f"{months_ru[d.month - 1]} {d.year}"


# --- Логика симуляции ---
def simulate_strategy(principal, rate_pct, total_months, start_date, min_pmt, max_pmt, inf_pct, switch_month):
    balance = principal
    data = []
    real_overpay_total = 0
    nom_overpay_total = 0
    cum_inf = 1.0
    inf_monthly = math.pow(1 + inf_pct / 100, 1 / 12) - 1
    daily_rate = rate_pct / 100 / 365
    current_date = start_date

    months_count = 0

    for m in range(int(total_months + 120)):
        if balance <= 10:
            break

        is_max_mode = m < switch_month
        payment = max_pmt if is_max_mode else min_pmt

        # Упрощенный расчет (как в оригинале: 30.44 дня в среднем)
        interest = balance * daily_rate * 30.44

        if balance + interest < payment:
            payment = balance + interest

        principal_part = payment - interest

        cum_inf *= (1 + inf_monthly)
        real_int = interest / cum_inf

        real_overpay_total += real_int
        nom_overpay_total += interest
        balance -= principal_part

        if balance < 0:
            balance = 0

        months_count += 1
        data.append({
            "date_obj": current_date,
            "Дата": current_date.strftime("%d.%m.%Y"),
            "Платеж": payment,
            "Режим": "MAX" if is_max_mode else "MIN",
            "% (Номинал)": interest,
            "Остаток долга": balance,
            "∑ Переплата (Real)": real_overpay_total,
            "is_max": is_max_mode
        })

        current_date = add_months(start_date, months_count)

    return {
        "schedule": pd.DataFrame(data),
        "realOverpayTotal": real_overpay_total,
        "nomOverpayTotal": nom_overpay_total,
        "months": months_count
    }


# --- Интерфейс (Боковая панель) ---
st.sidebar.markdown("### 1. Параметры кредита")
loan = st.sidebar.number_input("Сумма кредита (₽)", value=9000000, step=100000)
rate = st.sidebar.number_input("Ставка (% годовых)", value=20.0, step=0.1)
years = st.sidebar.number_input("Срок (лет)", value=20, step=1)
start_date = st.sidebar.date_input("Дата выдачи", value=datetime.date.today())

st.sidebar.markdown("---")
st.sidebar.markdown("### 2. Ваша стратегия")
inflation = st.sidebar.number_input("Ожидаемая инфляция (% год)", value=8.0, step=0.1)
target_overpay = st.sidebar.number_input("Целевая реальная переплата (₽)", value=4500000, step=100000)
st.sidebar.caption("Максимум, который вы готовы 'потерять' в покупательной способности денег.")
max_pmt = st.sidebar.number_input("Ваш Максимальный платеж (₽)", value=300000, step=10000)

calculate_btn = st.sidebar.button("Рассчитать и сравнить", type="primary", use_container_width=True)

# --- Основной блок ---
if calculate_btn or True:  # Авто-пересчет при изменении параметров
    months_total = years * 12
    r_month = rate / 100 / 12
    annuity = loan * (r_month * math.pow(1 + r_month, months_total)) / (math.pow(1 + r_month, months_total) - 1)

    if max_pmt <= annuity:
        st.error(
            f"Ошибка: Ваш максимальный платеж ({fmt_money(max_pmt)}) меньше или равен требованию банка ({fmt_money(annuity)}).")
    else:
        # 1. Базовая стратегия
        std_strategy = simulate_strategy(loan, rate, months_total, start_date, annuity, annuity, inflation, 0)

        # 2. Поиск оптимального месяца
        low, high = 0, months_total
        optimal_switch = 0

        min_poss = simulate_strategy(loan, rate, months_total, start_date, annuity, max_pmt, inflation, months_total)
        min_poss_overpay = min_poss['realOverpayTotal']

        if target_overpay <= min_poss_overpay:
            optimal_switch = months_total
        elif target_overpay >= std_strategy['realOverpayTotal']:
            optimal_switch = 0
        else:
            # Бинарный поиск
            while low <= high:
                mid = (low + high) // 2
                res = simulate_strategy(loan, rate, months_total, start_date, annuity, max_pmt, inflation, mid)

                if abs(res['realOverpayTotal'] - target_overpay) < 5000 or low == high:
                    optimal_switch = mid
                    break

                if res['realOverpayTotal'] > target_overpay:
                    low = mid + 1
                else:
                    high = mid - 1
                optimal_switch = mid

        opt_strategy = simulate_strategy(loan, rate, months_total, start_date, annuity, max_pmt, inflation,
                                         optimal_switch)

        # --- Вывод Вердикта ---
        switch_date = add_months(start_date, optimal_switch)
        date_str = get_ru_date(switch_date)

        if optimal_switch == 0:
            verdict_html = f"""
            <div style="background-color: #eff6ff; border-left: 4px solid #7c3aed; padding: 15px; border-radius: 6px; margin-bottom: 20px;">
                <div style="font-weight: bold; color: #1e3a8a; margin-bottom: 5px;">✅ Платите минимум</div>
                Ваша цель достижима даже при стандартных платежах ({fmt_money(annuity)}).
            </div>
            """
        elif optimal_switch >= std_strategy['months']:
            verdict_html = f"""
            <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 15px; border-radius: 6px; margin-bottom: 20px;">
                <div style="font-weight: bold; color: #991b1b; margin-bottom: 5px;">⚠️ Цель труднодостижима</div>
                Даже при максимальных платежах переплата составит {fmt_money(opt_strategy['realOverpayTotal'])}.
            </div>
            """
        else:
            verdict_html = f"""
            <div style="background-color: #eff6ff; border-left: 4px solid #7c3aed; padding: 15px; border-radius: 6px; margin-bottom: 20px;">
                <div style="font-weight: bold; color: #1e3a8a; margin-bottom: 5px;">⚡ Стратегия найдена</div>
                Чтобы ограничить реальную переплату суммой <b>{fmt_money(opt_strategy['realOverpayTotal'])}</b>:<br>
                1. Платите максимум <b>{fmt_money(max_pmt)}</b> до <b>{date_str}</b> (Месяц №{optimal_switch}).<br>
                2. Затем переключитесь на платеж банка <b>{fmt_money(annuity)}</b>.
            </div>
            """
        st.markdown(verdict_html, unsafe_allow_html=True)

        # --- Сравнение стратегий ---
        st.markdown("### Сравнение стратегий")

        std_avg = std_strategy['realOverpayTotal'] / std_strategy['months'] if std_strategy['months'] > 0 else 0
        opt_avg = opt_strategy['realOverpayTotal'] / opt_strategy['months'] if opt_strategy['months'] > 0 else 0

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Стандарт (Банк)", unsafe_allow_html=True)
            st.metric("Срок кредита", format_term(std_strategy['months']))
            st.metric("Переплата (Реальная)", fmt_money(std_strategy['realOverpayTotal']), delta="-С учетом инфляции",
                      delta_color="normal")
            st.metric("Средняя потеря/мес (Real)", fmt_money(std_avg))

        with col2:
            st.markdown('<h4 style="color: #7c3aed;">Оптимальная (Гибрид)</h4>', unsafe_allow_html=True)
            st.metric("Срок кредита", format_term(opt_strategy['months']),
                      delta=f"{opt_strategy['months'] - std_strategy['months']} мес.", delta_color="inverse")

            st.metric("Переплата (Реальная)", fmt_money(opt_strategy['realOverpayTotal']),
                      delta=f"{fmt_money(opt_strategy['realOverpayTotal'] - std_strategy['realOverpayTotal'])}",
                      delta_color="inverse")
            st.metric("Средняя потеря/мес (Real)", fmt_money(opt_avg))

        st.markdown("---")

        # --- График ---
        st.markdown("### Динамика остатка долга")
        df_std = std_strategy['schedule']
        df_opt = opt_strategy['schedule']

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_std['date_obj'], y=df_std['Остаток долга'],
            name='Стандарт (Баланс)',
            line=dict(color='#94a3b8', width=2)
        ))

        fig.add_trace(go.Scatter(
            x=df_opt['date_obj'], y=df_opt['Остаток долга'],
            name='Оптимально (Баланс)',
            line=dict(color='#7c3aed', width=2),
            fill='tozeroy', fillcolor='rgba(124, 58, 237, 0.1)'
        ))

        fig.update_layout(
            hovermode='x unified',
            margin=dict(l=0, r=0, t=20, b=0),
            yaxis=dict(title="Остаток долга (₽)", rangemode='tozero'),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- Детальный график (Фрагмент перехода) ---
        st.markdown("### Детальный график (Фрагмент перехода)")

        df = df_opt.copy()
        n = len(df)
        indices = set()

        for i in range(n):
            is_start = i < 3
            is_end = i > n - 4
            is_near_switch = (optimal_switch - 3 <= i <= optimal_switch + 3)
            if is_start or is_end or is_near_switch:
                indices.add(i)

        sorted_indices = sorted(list(indices))
        display_data = []
        last_idx = -1

        for idx in sorted_indices:
            if last_idx != -1 and idx - last_idx > 1:
                display_data.append({
                    "Дата": "...", "Платеж": None, "Режим": "...",
                    "% (Номинал)": None, "Остаток долга": None, "∑ Переплата (Real)": None
                })
            row = df.iloc[idx].to_dict()
            display_data.append({
                "Дата": row["Дата"],
                "Платеж": fmt_money(row["Платеж"]),
                "Режим": "MAX" if row.get("is_max") else "MIN",
                "% (Номинал)": fmt_money(row["% (Номинал)"]),
                "Остаток долга": fmt_money(row["Остаток долга"]),
                "∑ Переплата (Real)": fmt_money(row["∑ Переплата (Real)"])
            })
            last_idx = idx

        display_df = pd.DataFrame(display_data)


        # Настраиваем стиль DataFrame для Streamlit
        def highlight_mode(val):
            if val == 'MAX':
                return 'background-color: #fee2e2; color: #991b1b; font-weight: bold'
            elif val == 'MIN':
                return 'background-color: #e0f2fe; color: #075985; font-weight: bold'
            return ''


        styled_df = display_df.style.map(highlight_mode, subset=['Режим'])
        st.dataframe(styled_df, use_container_width=True, hide_index=True)