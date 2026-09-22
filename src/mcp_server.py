import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.db_connection import get_db_connection

# Create MCP server instance
app = Server("economic-data-server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools for querying economic data"""
    return [
        Tool(
            name="get_latest_indicator",
            description="Get the most recent value for an economic indicator",
            inputSchema={
                "type": "object",
                "properties": {
                    "indicator_id": {
                        "type": "string",
                        "description": "Indicator ID (GDP, FEDFUNDS, or UMCSENT)",
                        "enum": ["GDP", "FEDFUNDS", "UMCSENT"]
                    }
                },
                "required": ["indicator_id"]
            }
        ),
        Tool(
            name="get_indicator_history",
            description="Get historical data for an economic indicator",
            inputSchema={
                "type": "object",
                "properties": {
                    "indicator_id": {
                        "type": "string",
                        "description": "Indicator ID",
                        "enum": ["GDP", "FEDFUNDS", "UMCSENT"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of historical records to return",
                        "default": 10
                    }
                },
                "required": ["indicator_id"]
            }
        ),
        Tool(
            name="fetch_fresh_data",
            description="Fetch fresh data from FRED API and update database",
            inputSchema={
                "type": "object",
                "properties": {
                    "indicator_id": {
                        "type": "string",
                        "description": "Indicator ID to fetch, or 'all' for all indicators",
                        "enum": ["GDP", "FEDFUNDS", "UMCSENT", "all"]
                    }
                },
                "required": ["indicator_id"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute tool calls"""
    
    if name == "get_latest_indicator":
        indicator_id = arguments["indicator_id"]
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT date, value, fetched_at
            FROM economic_indicators
            WHERE indicator_id = %s
            ORDER BY date DESC
            LIMIT 1
        """, (indicator_id,))
        
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            date, value, fetched_at = result
            response = {
                "indicator": indicator_id,
                "date": str(date),
                "value": float(value),
                "fetched_at": str(fetched_at)
            }
            return [TextContent(
                type="text",
                text=json.dumps(response, indent=2)
            )]
        else:
            return [TextContent(
                type="text",
                text=f"No data found for {indicator_id}"
            )]
    
    elif name == "get_indicator_history":
        indicator_id = arguments["indicator_id"]
        limit = arguments.get("limit", 10)
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT date, value
            FROM economic_indicators
            WHERE indicator_id = %s
            ORDER BY date DESC
            LIMIT %s
        """, (indicator_id, limit))
        
        results = cur.fetchall()
        cur.close()
        conn.close()
        
        if results:
            history = [
                {"date": str(date), "value": float(value)}
                for date, value in results
            ]
            response = {
                "indicator": indicator_id,
                "count": len(history),
                "data": history
            }
            return [TextContent(
                type="text",
                text=json.dumps(response, indent=2)
            )]
        else:
            return [TextContent(
                type="text",
                text=f"No data found for {indicator_id}"
            )]
    
    elif name == "fetch_fresh_data":
        from src.fetch_data import fetch_and_store_indicator
        
        indicator_id = arguments["indicator_id"]
        
        if indicator_id == "all":
            indicators = [
                ("GDP", "GDP", 5),
                ("FEDFUNDS", "FEDFUNDS", 10),
                ("UMCSENT", "UMCSENT", 5)
            ]
            
            results = {}
            for ind_id, series_id, limit in indicators:
                try:
                    inserted = fetch_and_store_indicator(ind_id, series_id, limit)
                    results[ind_id] = f"{inserted} new records"
                except Exception as e:
                    results[ind_id] = f"Error: {str(e)}"
            
            return [TextContent(
                type="text",
                text=json.dumps(results, indent=2)
            )]
        else:
            # Fetch single indicator
            try:
                inserted = fetch_and_store_indicator(indicator_id, indicator_id, 10)
                return [TextContent(
                    type="text",
                    text=f"Fetched {inserted} new records for {indicator_id}"
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=f"Error fetching {indicator_id}: {str(e)}"
                )]
    else:
        return [TextContent(
            type="text",
            text=f"Unknown tool: {name}"
        )]
            

async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())