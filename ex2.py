import streamlit as st
import pandas as pd
import plotly.express as px

# 1. Базовая настройка страницы (широкий формат выглядит лучше для дашбордов)
st.set_page_config(page_title="Аналитика Заказов", page_icon="📊", layout="wide")

# Немного кастомного CSS, чтобы убрать лишние отступы сверху
st.markdown("""
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    </style>
""", unsafe_allow_html=True)

st.title('📊 Дашборд аналитики активности', anchor=None)


# 2. Кэшированная загрузка и предобработка данных (КРИТИЧНО для 5.7 млн строк)
@st.cache_data(show_spinner="Загрузка и обработка данных...")
def load_data(file):
    df = pd.read_csv(file)

    # Оптимизация типов данных для ускорения работы
    df['AddedOn'] = pd.to_datetime(df['AddedOn'])
    df['ChangedOn'] = pd.to_datetime(df['ChangedOn'])
    df['Status'] = df['Status'].astype('category')

    # Добавляем удобные колонки для группировки
    df['Date'] = df['AddedOn'].dt.date
    df['Hour'] = df['AddedOn'].dt.hour
    return df


# 3. Сайдбар для загрузки файла
with st.sidebar:
    st.header("⚙️ Источник данных")
    data_file = st.file_uploader('Загрузите CSV файл', type="csv")

if data_file is not None:
    df = load_data(data_file)

    # --- Сайдбар: Фильтры ---
    with st.sidebar:
        st.markdown("### 🔍 Фильтры")

        # Фильтр по датам
        min_date = df['Date'].min()
        max_date = df['Date'].max()
        date_range = st.date_input("Период", [min_date, max_date], min_value=min_date, max_value=max_date)

        # Фильтр по городам (ограничиваем выборку по умолчанию, чтобы не перегрузить график)
        cities = df['CityId'].unique()
        default_cities = cities[:3] if len(cities) > 3 else cities
        selected_cities = st.multiselect("Города (CityId):", options=cities, default=default_cities)

        # Фильтр по статусам
        statuses = df['Status'].unique()
        selected_statuses = st.multiselect("Статусы:", options=statuses, default=statuses)

    # 4. Применение фильтров к датафрейму
    if len(date_range) == 2:
        start_date, end_date = date_range
        mask = (
                (df['Date'] >= start_date) &
                (df['Date'] <= end_date) &
                (df['CityId'].isin(selected_cities)) &
                (df['Status'].isin(selected_statuses))
        )
        df_filtered = df[mask]
    else:
        df_filtered = df

    # --- Главный экран: Метрики (KPIs) ---
    st.markdown("### 📈 Ключевые показатели")
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Всего записей", f"{len(df_filtered):,}".replace(',', ' '))
    col2.metric("Уникальных пользователей", f"{df_filtered['UserId'].nunique():,}".replace(',', ' '))
    col3.metric("Уникальных ресторанов", f"{df_filtered['RestaurantId'].nunique():,}".replace(',', ' '))
    col4.metric("Активных городов", len(selected_cities))

    st.markdown("---")

    # --- Графики (Верхний ряд) ---
    col_chart1, col_chart2 = st.columns([2, 1])

    with col_chart1:
        st.markdown("#### Динамика записей по дням")
        # Агрегируем данные перед передачей в график — это сэкономит память
        daily_data = df_filtered.groupby(['Date', 'CityId']).size().reset_index(name='Count')

        fig_line = px.line(
            daily_data,
            x='Date',
            y='Count',
            color='CityId',
            markers=True,
            template="plotly_white",
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig_line.update_layout(xaxis_title="", yaxis_title="Количество", legend_title="Город",
                               margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_line, use_container_width=True)

    with col_chart2:
        st.markdown("#### Распределение статусов")
        status_data = df_filtered['Status'].value_counts().reset_index()
        status_data.columns = ['Status', 'Count']

        fig_pie = px.pie(
            status_data,
            names='Status',
            values='Count',
            hole=0.4,  # Делает график "бубликом" (Donut chart)
            template="plotly_white",
            color_discrete_sequence=px.colors.sequential.Teal
        )
        fig_pie.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")

    # --- Графики (Нижний ряд) ---
    col_chart3, col_chart4 = st.columns(2)

    with col_chart3:
        st.markdown("#### Топ-10 ресторанов по загрузке")
        top_restaurants = df_filtered['RestaurantId'].value_counts().head(10).reset_index()
        top_restaurants.columns = ['RestaurantId', 'Count']
        # Укорачиваем длинные UUID для красоты на оси Y
        top_restaurants['Restaurant_Short'] = top_restaurants['RestaurantId'].astype(str).str[:8] + '...'

        fig_bar = px.bar(
            top_restaurants,
            x='Count',
            y='Restaurant_Short',
            orientation='h',
            template="plotly_white",
            color='Count',
            color_continuous_scale='Blues'
        )
        # Сортируем так, чтобы лидер был сверху
        fig_bar.update_layout(yaxis={'categoryorder': 'total ascending'}, margin=dict(l=0, r=0, t=10, b=0),
                              yaxis_title="")
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_chart4:
        st.markdown("#### Активность по часам (когда добавляют записи)")
        hourly_data = df_filtered.groupby('Hour').size().reset_index(name='Count')

        fig_hourly = px.bar(
            hourly_data,
            x='Hour',
            y='Count',
            template="plotly_white",
            color_discrete_sequence=['#5C93C4']
        )
        fig_hourly.update_layout(
            xaxis_title="Час дня",
            yaxis_title="",
            xaxis=dict(tickmode='linear', tick0=0, dtick=1),
            margin=dict(l=0, r=0, t=10, b=0)
        )
        st.plotly_chart(fig_hourly, use_container_width=True)

else:
    # Инструкция, пока файл не загружен
    st.info("👈 Пожалуйста, загрузите CSV файл в боковой панели, чтобы увидеть дашборд.")