# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

from typing import Annotated

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : index.py
# @Software: PyCharm
from fastapi import APIRouter, Depends

from core.models.user import LoginUserIn
from core.security import get_current_user, require_scopes
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BrainKB Query Service</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                margin: 0;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                min-height: 100vh;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: rgba(255, 255, 255, 0.1);
                padding: 30px;
                border-radius: 15px;
                backdrop-filter: blur(10px);
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            }
            h1 {
                text-align: center;
                margin-bottom: 30px;
                font-size: 2.5em;
                text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
            }
            .info-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin: 30px 0;
            }
            .info-card {
                background: rgba(255, 255, 255, 0.1);
                padding: 20px;
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            .info-card h3 {
                margin-top: 0;
                color: #ffd700;
            }
            .feature-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin: 30px 0;
            }
            .feature-card {
                background: rgba(255, 255, 255, 0.1);
                padding: 20px;
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            .feature-card h3 {
                margin-top: 0;
                color: #ffd700;
            }
            .endpoint-list {
                background: rgba(0, 0, 0, 0.2);
                padding: 20px;
                border-radius: 10px;
                margin: 20px 0;
            }
            .endpoint-list h3 {
                margin-top: 0;
                color: #ffd700;
            }
            .endpoint {
                margin: 10px 0;
                padding: 10px;
                background: rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                border-left: 4px solid #ffd700;
            }
            .method {
                font-weight: bold;
                color: #ffd700;
            }
            .url {
                font-family: monospace;
                color: #87ceeb;
            }
            .description {
                color: #e0e0e0;
                font-size: 0.9em;
                margin-top: 5px;
            }
            .features-list {
                list-style: none;
                padding: 0;
            }
            .features-list li {
                padding: 8px 0;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }
            .features-list li:before {
                content: "✓ ";
                color: #ffd700;
                font-weight: bold;
            }
            .quick-links {
                text-align: center;
                margin: 30px 0;
            }
            .quick-links a {
                display: inline-block;
                margin: 10px;
                padding: 12px 24px;
                background: rgba(255, 255, 255, 0.2);
                color: white;
                text-decoration: none;
                border-radius: 25px;
                transition: all 0.3s ease;
                border: 1px solid rgba(255, 255, 255, 0.3);
            }
            .quick-links a:hover {
                background: rgba(255, 255, 255, 0.3);
                transform: translateY(-2px);
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            }
            .footer {
                text-align: center;
                margin-top: 40px;
                padding-top: 20px;
                border-top: 1px solid rgba(255, 255, 255, 0.2);
                color: #e0e0e0;
            }
            .status {
                display: inline-block;
                padding: 5px 15px;
                background: rgba(76, 175, 80, 0.3);
                border-radius: 20px;
                font-size: 0.9em;
                border: 1px solid rgba(76, 175, 80, 0.5);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 BrainKB Chat Service</h1>

            <div class="info-grid">
                <div class="info-card">
                    <h3>📋 Service Information</h3>
                    <p><strong>Version:</strong> 1.0.0</p>
                    <p><strong>Status:</strong> <span class="status">running</span></p>
                    <p><strong>Description:</strong> 
                    Query service, one of the component of BrainKB that allows ingestion/retrieval of the data from the
                    graph databse.
                    </p>
                    <p><strong>Contact:</strong> tekraj@mit.edu</p>
                </div>

                <div class="info-card">
                    <h3>✨ Features</h3>
                    <ul class="features-list">  
                        <li>Knowledge graph integration</li> 
                    </ul>
                </div>
            </div>

        

            <div class="endpoint-list">
                <h3>📡 API Endpoints</h3>
                <div class="endpoint">
                    <span class="method">POST</span> <span class="url">/register</span>
                    <div class="description">JWT account registration (Needs to be manually activated).</div>
                </div>
                <div class="endpoint">
                    <span class="method">POST</span> <span class="url">/token</span>
                    <div class="description">Endpoint to obtain the JWT token</div>
                </div>
                <div class="endpoint">
                    <span class="method">POST</span> <span class="url">/insert/knowledge-graph-triples</span>
                    <div class="description">Insert KGs (raw format) into the database.</div>
                </div>
                <div class="endpoint">
                    <span class="method">POST</span> <span class="url">/insert/files/structured-resource-json-to-kg</span>
                    <div class="description">Upload and insert multiple JSON files as knowledge graph triples.</div>
                </div>
                <div class="endpoint">
                    <span class="method">POST</span> <span class="url">/insert/files/knowledge-graph-triples</span>
                    <div class="description">Upload and insert knowledge graph triples from multiple files (TTL or JSON-LD format).</div>
                </div>
                
                
                                <div class="endpoint">
                    <span class="method">GET</span> <span class="url">/query/sparql/</span>
                    <div class="description">API endpoint that allows querying the graph database via SPARQL query.</div>
                </div>
                <div class="endpoint">
                    <span class="method">GET</span> <span class="url">/query/registered-named-graphs</span>
                    <div class="description">Get the list of registered named graphs.</div>
                </div>
                <div class="endpoint">
                    <span class="method">GET</span> <span class="url">/api/rapid-release/statistics</span>
                    <div class="description">This endpoint gets the statistics, i.e., counts, about the rapid release data, e.g., donors sample count.</div>
                </div>
                
                <div class="endpoint">
                    <span class="method">GET</span> <span class="url">/api/rapid-release/categories?limit=X&offset=Y</span>
                    <div class="description">This endpoint gets all the unique rapid release categories, e.g., Donor</div>
                </div>
                
                 <div class="endpoint">
                    <span class="method">GET</span> <span class="url">/api/rapid-release/category?category_name=XXX&limit=XX&offset=XX</span>
                    <div class="description">This endpoint gets the all list of data by category, e.g., TissueSample. The fetched data are grouped by rapid ID (or subject) and the values (predicate or property or relationships and objects) are concatenated, separated by comma.</div>
                </div>
                
                
                
                <div class="endpoint">
                    <span class="method">GET</span> <span class="url">/docs</span>
                    <div class="description">Interactive API documentation</div>
                </div>
                <div class="endpoint">
                    <span class="method">GET</span> <span class="url">/redoc</span>
                    <div class="description">Alternative API documentation</div>
                </div>
            </div>

            <div class="quick-links">
                <a href="/docs" target="_blank">📚 API Documentation</a>  
                <a href="/redoc" target="_blank">📖 Alternative Docs</a>
            </div>

            <div class="footer">
                <p>©BrainKB™ & Senseable Intelligence Group. All Rights Reserved. </strong> | <a href="https://sensein.group/" style="color: #ffd700;">Website Senseable Intelligence Group</a></p>
                <p>Version 1.0.0 | Powered by FastAPI & PostgreSQL</p>
            </div>
        </div>
    </body>
    </html>
    """


@router.get(
    "/token-check",
    dependencies=[Depends(require_scopes(["read"]))],
    include_in_schema=False,
)
async def token_check(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    return {"message": "token check passed success"}
