import numpy
import os
import pandas as pd
import dotenv
import geopandas as gpd
import folium
from sqlalchemy import create_engine

import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output

import plotly.express as px
import plotly.figure_factory as ff

dotenv.load_dotenv()
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD')

dbms = 'postgresql'
package = 'psycopg'
user = 'postgres'
password = POSTGRES_PASSWORD
host = 'localhost'
port = '5432'
db = 'demographic'

engine = create_engine(f"{dbms}+{package}://{user}:{password}@{host}:{port}/{db}")

external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']

app = dash.Dash(__name__, external_stylesheets=external_stylesheets)

tract_shapefile = 'data/tl_2025_51_tract/tl_2025_51_tract.shp'
census_data_path = 'data/VA_census_data.csv'

tract_gdf = gpd.read_file(tract_shapefile)
census_data = pd.read_csv(census_data_path)

tract_gdf['GEOID'] = tract_gdf['GEOID'].astype(str)
census_data['GEOID'] = census_data['GEOID'].astype(str)

merged_gdf = tract_gdf.merge(census_data, on='GEOID', how='left')

map_variables = {
    'Median Household Income': 'Medium_Household_Income',
    'Total Population': 'Total_Population',
    'Male Median Age': 'Median_Age_by_Sex_Male',
    'Female Median Age': 'Median_Age_by Sex_Female'
}
variable_options = [{'label': k, 'value': v} for k, v in map_variables.items()]


app = dash.Dash(__name__)
app.title = "US Census Dashboard"

app.layout = html.Div([

    html.H1("Which State to Go?"),

    html.Div([
        
        dcc.Markdown("### Select State"),
        dcc.Dropdown(
            id='map-variable',
            options=variable_options,
            value='Medium_Household_Income',
            clearable=False
        )

    ], style={'width': '25%', 'float': 'left', 'padding': '20px'}),

    html.Div([
        html.Iframe(
            id='folium-map',
            width='100%',
            height='700'
        )
    ], style={'width': '70%', 'float': 'right', 'padding': '20px'})

])


@app.callback(
    Output('folium-map', 'srcDoc'),
    [
        Input('state-dropdown', 'value'),
        Input('map-variable', 'value')
    ]
)
def update_map(state_fips, variable):

    filtered_gdf = merged_gdf[merged_gdf['STATEFP'] == state_fips]

    if filtered_gdf.empty:
        filtered_gdf = merged_gdf

    center = filtered_gdf.geometry.unary_union.centroid
    m = folium.Map(location=[center.y, center.x], zoom_start=7)

    def style_function(feature):
        value = feature['properties'].get(variable)
        if value is None:
            return {'fillColor': 'white', 'weight': 0.5}
        elif value < 20000:
            return {'fillColor': 'red', 'weight': 0.5}
        elif value < 50000:
            return {'fillColor': 'orange', 'weight': 0.5}
        elif value < 90000:
            return {'fillColor': 'lightgreen', 'weight': 0.5}
        else:
            return {'fillColor': 'darkgreen', 'weight': 0.5}

    folium.GeoJson(
        filtered_gdf,
        style_function=style_function,
        tooltip=folium.features.GeoJsonTooltip(
            fields=[
                'GEOID',
                'Total_Population',
                'Medium_Household_Income'
            ],
            aliases=[
                'Tract GEOID',
                'Population',
                'Median Household Income'
            ],
            localize=True
        )
    ).add_to(m)

    return m.get_root().render()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8050)
