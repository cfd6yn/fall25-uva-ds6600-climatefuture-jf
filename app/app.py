import os
import numpy as np
import requests
import pandas as pd
import geopandas as gpd
import dotenv
from sqlalchemy import create_engine

import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.express as px

dotenv.load_dotenv()
CENSUS_KEY = os.getenv("censuskey")

external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']

# Create features that we need, but won't change depending on what the user does
# Load state shapefile
state_shapefile = 'data/tl_2025_us_state/tl_2025_us_state.shp' 
states_gdf = gpd.read_file(state_shapefile)

# Compute state centroids
states_proj = states_gdf.to_crs(epsg=2163)
states_proj["centroid"] = states_proj.geometry.centroid
states_gdf["center_lon"] = states_proj.centroid.to_crs(epsg=4326).x
states_gdf["center_lat"] = states_proj.centroid.to_crs(epsg=4326).y

df_states = states_gdf[["GEOID", "STUSPS", "NAME", "center_lat", "center_lon", "geometry"]]
df_states_sorted = df_states.sort_values("NAME")

df_state_lookup = df_states[["GEOID", "STUSPS"]].copy()
df_state_lookup.rename(columns={'STUSPS': 'State_Abbr'}, inplace=True) 

state_options = [
    {"label": f"{row.NAME} ({row.STUSPS})", "value": row.GEOID}
    for _, row in df_states_sorted.iterrows()
]

# Variables to fetch from ACS
census_code = 'B19013_001E'
variables = {
    'Total_Population': 'B01003_001E',
    'Median_Age_by_Sex_Male': 'B01002_002E',
    'Median_Age_by_Sex_Female': 'B01002_003E',
    'Medium_Household_Income': 'B19013_001E',
    'Management_business_science_arts': 'C24050_002E',
    'Service': 'C24050_003E',
    'Natural_Resources_Construction_Maintenance': 'C24050_005E',
    'Production_Transportation_Material_Moving': 'C24050_006E'
}

YEAR = "2023"
BASE_URL = f"https://api.census.gov/data/{YEAR}/acs/acs5"

def load_state_data(state_fips):
    """Fetches Census data and TIGER tract geometry, merges them, and prepares income classes."""
    variables_str = ",".join(variables.values())
    
    url = (
        f"{BASE_URL}?get=NAME,{variables_str}&for=tract:*&in=state:{state_fips}&key={CENSUS_KEY}"
    )
    r = requests.get(url)
    
    if r.status_code != 200 or not r.json():
        print(f"Error fetching data for FIPS {state_fips}: Status {r.status_code}")
        return gpd.GeoDataFrame()

    df = pd.DataFrame(r.json()[1:], columns=r.json()[0])
    df.rename(columns={v: k for k, v in variables.items()}, inplace=True)
    
    numerical_cols = list(variables.keys())
    df[numerical_cols] = df[numerical_cols].apply(pd.to_numeric, errors="coerce")

    df["GEOID"] = df["state"] + df["county"] + df["tract"]

    tracts_url = f"https://www2.census.gov/geo/tiger/TIGER{YEAR}/TRACT/tl_{YEAR}_{state_fips}_tract.zip"
    try:
        tracts = gpd.read_file(tracts_url)
    except Exception as e:
        print(f"Error loading tract geometry for FIPS {state_fips}: {e}")
        return gpd.GeoDataFrame()

    tracts['GEOID'] = tracts['GEOID'].astype(str)
    df['GEOID'] = df['GEOID'].astype(str)
    gdf = tracts.merge(df, on="GEOID", how="inner")
    
    gdf = gdf.dropna(subset=['Medium_Household_Income'])

    try:
        gdf["income_class"] = pd.qcut(
            gdf["Medium_Household_Income"], q=9, duplicates="drop", labels=False
        )

        gdf['income_class_num'] = gdf['income_class']
        gdf["income_class_num"] = gdf["income_class_num"].max() - gdf["income_class_num"]
    except ValueError:
        print("Warning: Not enough unique income values for 9 quantiles. Using 5.")
        gdf["income_class"] = pd.qcut(
            gdf["Medium_Household_Income"], q=5, duplicates="drop", labels=False
        )
        gdf['income_class_num'] = gdf['income_class']
        gdf["income_class_num"] = gdf["income_class_num"].max() - gdf["income_class_num"]
        
    return gdf

# Fetch disaster frequency data
disaster_freq_url = 'https://www.ncei.noaa.gov/access/billions/state-freq-data.csv'
df_freq = pd.read_csv(disaster_freq_url, skiprows=1)

df_freq.columns = df_freq.columns.str.strip().str.lower()

df_freq.rename(columns={
    'state': 'State_Abbr',
    'year': 'Year'
}, inplace=True)

df_freq.rename(columns={'State': 'State_Abbr'}, inplace=True)
df_freq['Year'] = pd.to_numeric(df_freq['Year'])

DISASTER_FREQ_DF = df_freq.melt(
    id_vars=['Year', 'State_Abbr'],
    value_vars=['drought', 'flooding', 'freeze', 'severe storm', 'tropical cyclone', 'wildfire', 'winter storm'],
    var_name='Disaster_Type',
    value_name='Frequency'
)

DISASTER_FREQ_DF = DISASTER_FREQ_DF.merge(
    df_state_lookup, 
    on='State_Abbr', 
    how='left'
)
DISASTER_FREQ_DF.rename(columns={'GEOID': 'State_FIPS'}, inplace=True)

DISASTER_FREQ_DF = DISASTER_FREQ_DF[DISASTER_FREQ_DF['Frequency'] > 0].copy()
DISASTER_FREQ_DF.dropna(subset=['State_FIPS'], inplace=True)
DISASTER_FREQ_DF['Frequency'] = pd.to_numeric(DISASTER_FREQ_DF['Frequency'], errors='coerce')

# Fetch disaster cost data
disaster_cost_url = 'https://www.ncei.noaa.gov/access/billions/state-cost-data.csv'
df_cost = pd.read_csv(disaster_cost_url, skiprows=1)
df_cost.columns = df_cost.columns.str.strip()
df_cost.rename(columns={'state': 'State_Abbr'}, inplace=True)

cost_value_vars = [
    'drought', 'flooding', 'freeze', 'severe storm', 
    'tropical cyclone', 'wildfire', 'winter storm'
]

DISASTER_COST_DF = df_cost.melt(
    id_vars=['State_Abbr'],
    value_vars=cost_value_vars, 
    var_name='Disaster_Type',
    value_name='Total_Cost_Millions'
)

DISASTER_COST_DF = DISASTER_COST_DF.merge(
    df_state_lookup, 
    on='State_Abbr', 
    how='left'
)

DISASTER_COST_DF.rename(columns={'GEOID': 'State_FIPS'}, inplace=True)

DISASTER_COST_DF['Total_Cost_Millions'] = (
    DISASTER_COST_DF['Total_Cost_Millions']
    .astype(str)
    .replace('[,]', '', regex=True)
    .apply(pd.to_numeric, errors='coerce')
)

DISASTER_COST_DF.dropna(subset=['State_FIPS', 'Total_Cost_Millions'], inplace=True)
DISASTER_COST_DF = DISASTER_COST_DF[DISASTER_COST_DF['Total_Cost_Millions'] > 0].copy()

# Define the Dash app
app = dash.Dash(__name__, external_stylesheets=external_stylesheets)
server = app.server

# Populate the dashboard layout
app.layout = html.Div([
    html.Div(style={
        'display': 'flex', 
        'alignItems': 'center', 
        'justifyContent': 'space-between', 
        'padding': '0 20px 10px 20px', 
        'borderBottom': '1px solid #eee'
    }, children=[
        
        html.H1("Where Do You Want to Live?", 
                style={'textAlign': 'left', 'marginBottom': '0', 'flexGrow': '1'}),
        
        html.Div([
            dcc.Markdown("**Select State:**", style={'marginRight': '10px', 'display': 'inline-block'}),
            dcc.Dropdown(
                id="state-dropdown", 
                options=state_options, 
                value="51",
                clearable=False,
                style={'width': '250px', 'display': 'inline-block'}
            )
        ], style={'display': 'flex', 'alignItems': 'center'})
    ]), 
    
    html.Div(style={
        'display': 'flex', 
        'alignItems': 'flex-start', 
        'padding': '10px 20px 0 20px', 
        'gap': '20px'
    }, children=[

        html.Div(style={
            'flex': '0 0 25%',
            'maxWidth': '25%',
            'padding': '8px 0',
            'boxSizing': 'border-box',
            'display': 'flex', 
            'flexDirection': 'column',
            'gap': '5px' 
        }, children=[

            html.Div([
                html.H6("Billion-Dollar Disaster Frequency", 
                        style={'textAlign': 'left', 'marginBottom': '5px'}),
                dcc.Graph(id="frequency-scatter-plot", style={'height': '65vh', 'width': '100%'})
            ], style={'marginBottom': '0px'}), 

            html.Div([
                html.H6("Total Disaster Cost 1980-2024 (Billion USD)", 
                        style={'textAlign': 'left', 'marginBottom': '5px'}),
                dcc.Graph(id="cost-bar-chart", style={'height': '25vh', 'width': '100%'})
            ], style={'marginTop': '0px'})
        ]),
    
        html.Div([
            dcc.Graph(id="map", style={'height': '100vh', 'width': '100%'}) 
        ], style={
            'flex': '1', 
            'padding': '8px 0',
            'boxSizing': 'border-box',
        })
    ])
])


# Define the 'callbacks' -- user input -> output functions
@app.callback(
    Output("map", "figure"),
    Input("state-dropdown", "value")
)
def display_choropleth(state_fips):
    gdf = load_state_data(state_fips)

    if gdf.empty:
        return {
            'layout': {
                'title': f'No Data Found for State FIPS: {state_fips}'
            }
        }

    state_row = df_states[df_states["GEOID"] == state_fips].iloc[0]
    center = {"lat": state_row.center_lat, "lon": state_row.center_lon}
    state_name = state_row.NAME

    zoom_level = 6.3

    fig = px.choropleth_mapbox(
        gdf,
        geojson=gdf.geometry.__geo_interface__,
        locations=gdf.index,
        color="income_class_num",
        color_continuous_scale=px.colors.sequential.Plasma,
        opacity=0.6,
        mapbox_style="carto-positron",
        hover_data={
            'NAME_y': True,
            'GEOID': True,
            'Total_Population': ':,',
            'Medium_Household_Income': ':$,.0f',
            'Median_Age_by_Sex_Male': ':.1f',
            'Median_Age_by_Sex_Female': ':.1f',
            'Management_business_science_arts': ':,',
            'Service': ':,',
            'Natural_Resources_Construction_Maintenance': ':,',
            'Production_Transportation_Material_Moving': ':,',
            'income_class_num': False 
        },
    )

    fig.update_layout(
        mapbox={
            "center": center, 
            "zoom": zoom_level,
            "style": "carto-positron"
        },
        margin={"r":0,"t":0,"l":0,"b":0},
        title=f'Median Household Income by Census Tract in {state_name}', 
        coloraxis_colorbar=dict(
            title="Income Class",
            lenmode="fraction", len=0.7
        )
    )

    return fig

@app.callback(
    Output("frequency-scatter-plot", "figure"),
    Input("state-dropdown", "value")
)
def update_frequency_scatter(state_fips):
    df = DISASTER_FREQ_DF[DISASTER_FREQ_DF['State_FIPS'] == state_fips]
    
    state_row = df_states[df_states["GEOID"] == state_fips].iloc[0]
    state_name = state_row.NAME

    fig = px.scatter(
        df, 
        x='Frequency', 
        y='Year', 
        color='Disaster_Type', 
        labels={'Year': 'Year', 'Frequency': 'Frequency', 'Disaster_Type': 'Disaster Type'}
    )
    
    fig.update_traces(
        mode='lines+markers',
        marker={'size': 8}
    )

    fig.update_layout(yaxis={'dtick': 5, 'tick0': 1980, 'showgrid': True},

        legend=dict(
            orientation="h",      
            yanchor="bottom", 
            y=-0.18, 
            xanchor="center", 
            x=0.5,
            font=dict(size=8)  
        ),
        margin=dict(l=20, r=20, t=20, b=30)
    )
    
    return fig

@app.callback(
    Output("cost-bar-chart", "figure"),
    Input("state-dropdown", "value")
)
def update_cost_bar_chart(state_fips):
    df_filtered = DISASTER_COST_DF[DISASTER_COST_DF['State_FIPS'] == state_fips].copy()
    
    if df_filtered.empty:
        fig = {} 
    else:
        state_row = df_states[df_states["GEOID"] == state_fips].iloc[0]
        state_name = state_row.NAME
        
        df_filtered['Cost_Billion'] = df_filtered['Total_Cost_Millions'] / 1000
        
        fig = px.bar(
            df_filtered,
            x='Disaster_Type',
            y='Cost_Billion',
            color='Disaster_Type',
            labels={'Cost_Billion': 'Cost (Billions USD)', 'Disaster_Type': ''}, 
            height=300 
        )
        
        fig.update_layout(
            showlegend=False,
            xaxis={'title': None, 'tickangle': 45},
            yaxis={'tickformat': '$.2f'}, 
            margin=dict(l=40, r=10, t=30, b=10)
        )
        
    return fig

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)
