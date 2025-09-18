"""
Avaya Mock Service

This module provides a mock implementation of the Avaya API for development
and testing purposes. It simulates call search and audio replay functionality
with realistic data generation.

Features:
- Call search API with date range filtering
- Audio file serving for call replay
- Consistent call-to-audio mapping
- Realistic call data generation
- XML response formatting compatible with real Avaya systems

Author: AgentScoring Team
Date: 2025-09-15
"""

import datetime
import hashlib
import os
import random
from typing import Dict, List, Any

from fastapi import FastAPI, Query, Response
from fastapi.responses import PlainTextResponse


# FastAPI application instance
app = FastAPI(title="Avaya Mock API", version="1.0.0")

# Directory configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(SCRIPT_DIR, "audio")

# Initialize audio files list
audio_files = []
if os.path.exists(AUDIO_DIR):
    audio_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith(".wav")]

# Global caches for consistency
call_audio_map: Dict[str, str] = {}  # call_id -> audio_file mapping
daily_calls_cache: Dict[datetime.date, List[Dict[str, Any]]] = {}


def get_audio_for_call(call_id: str) -> str:
    """
    Get consistent audio file path for a given call ID.
    
    Uses MD5 hashing to ensure the same call ID always returns
    the same audio file, providing consistency across requests.
    
    Args:
        call_id: Unique identifier for the call
        
    Returns:
        str: Full path to the audio file
        
    Raises:
        IndexError: If no audio files are available
    """
    if not audio_files:
        raise IndexError("No audio files available in audio directory")
        
    if call_id not in call_audio_map:
        # Use hash for deterministic file selection
        hash_value = int(hashlib.md5(call_id.encode()).hexdigest(), 16)
        idx = hash_value % len(audio_files)
        call_audio_map[call_id] = audio_files[idx]
    
    return os.path.join(AUDIO_DIR, call_audio_map[call_id])


def generate_daily_calls(date: datetime.date) -> List[Dict[str, Any]]:
    """
    Generate realistic call data for a specific date.
    
    Creates 10,000 simulated calls with random timestamps throughout
    the day and realistic call metadata matching Avaya format.
    
    Args:
        date: Date for which to generate calls
        
    Returns:
        List[Dict]: List of call dictionaries with metadata
    """
    if date in daily_calls_cache:
        return daily_calls_cache[date]

    calls = []
    base_datetime = datetime.datetime.combine(date, datetime.time(0, 0, 0))
    seconds_in_day = 24 * 3600
    
    # Generate unique random timestamps for the day
    chosen_seconds = random.sample(range(seconds_in_day), 4000)

    for sec in chosen_seconds:
        # Calculate call timestamp
        timestamp = base_datetime + datetime.timedelta(seconds=sec)
        call_id = str(random.randint(10**14, 10**15 - 1))
        agent_id = random.randint(1000, 9999)
        
        # Generate realistic call metadata
        call_data = {
            "contactid": f"{call_id}_2",
            "startedat": timestamp,
            "owner": str(random.randint(1000, 9999)),
            "otherparties": (
                f"{random.randint(100000, 999999)}, "
                f"4603 (agent{agent_id}.247)"
            ),
            "services": f"{random.randint(20000, 29999)} (ATC_MASS_VIE_The)",
            "skills": f"{random.randint(20000, 29999)} (ATC_MASS_VIETHE)",
            "udfs": "",
            "inums": call_id,
            "agents": f"{agent_id} (agent{agent_id}.247)",
            "switchcallid": str(random.randint(10**17, 10**18 - 1))
        }
        
        calls.append(call_data)

    # Cache for consistency
    daily_calls_cache[date] = calls
    return calls


@app.get("/searchapi")
def searchapi(
    command: str = Query(..., description="API command to execute"),
    layout: str = Query(None, description="Search layout configuration"),
    param1_startedat: str = Query(None, description="Start date (DD/MM/YY)"),
    param2_startedat: str = Query(None, description="Start time (HH:MM:SS)"),
    param3_startedat: str = Query(None, description="End date (DD/MM/YY)"),
    param4_startedat: str = Query(None, description="End time (HH:MM:SS)"),
    operator_startedat: str = Query(None, description="Date range operator"),
    id: str = Query(None, description="Call ID for replay command"),
):
    """
    Main API endpoint for call search and audio replay.
    
    Supports two main commands:
    - search: Returns XML list of calls within date range
    - replay: Returns audio file content for specific call ID
    
    Args:
        command: API command ('search' or 'replay')
        layout: Search layout (unused in mock)
        param1_startedat: Start date in DD/MM/YY format
        param2_startedat: Start time in HH:MM:SS format
        param3_startedat: End date in DD/MM/YY format
        param4_startedat: End time in HH:MM:SS format
        operator_startedat: Date range operator (unused in mock)
        id: Call ID for audio replay
        
    Returns:
        Response: XML response for search, audio data for replay
    """
    if command == "search":
        # Parse datetime range from parameters
        try:
            start_dt = datetime.datetime.strptime(
                f"{param1_startedat} {param2_startedat}", 
                "%d/%m/%y %H:%M:%S"
            )
            end_dt = datetime.datetime.strptime(
                f"{param3_startedat} {param4_startedat}", 
                "%d/%m/%y %H:%M:%S"
            )
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid date format: {e}"}

        # Build XML response
        results_xml = '<?xml version="1.0" encoding="UTF-8"?><results>'

        # Process each day in the range
        current_date = start_dt.date()
        while current_date <= end_dt.date():
            calls = generate_daily_calls(current_date)

            # Filter calls by time range
            for call in calls:
                if start_dt <= call["startedat"] <= end_dt:
                    results_xml += f"""
                    <result contactid="{call['contactid']}">
                        <field name="startedat">{call['startedat'].isoformat()}</field>
                        <field name="owner">{call['owner']}</field>
                        <field name="otherparties">{call['otherparties']}</field>
                        <field name="services">{call['services']}</field>
                        <field name="skills">{call['skills']}</field>
                        <field name="udfs">{call['udfs']}</field>
                        <field name="inums">{call['inums']}</field>
                        <field name="agents">{call['agents']}</field>
                        <field name="switchcallid">{call['switchcallid']}</field>
                    </result>
                    """
            
            current_date += datetime.timedelta(days=1)

        results_xml += "</results>"
        return PlainTextResponse(
            content=results_xml, 
            media_type="application/xml"
        )

    elif command == "replay" and id:
        # Serve audio file for the specified call ID
        try:
            audio_path = get_audio_for_call(id)
            
            if not os.path.exists(audio_path):
                return {"error": f"Audio file not found for call ID: {id}"}
                
            with open(audio_path, "rb") as audio_file:
                audio_data = audio_file.read()
                
            return Response(
                content=audio_data, 
                media_type="audio/wav",
                headers={
                    "Content-Disposition": f"attachment; filename=call_{id}.wav"
                }
            )
            
        except (IndexError, OSError) as e:
            return {"error": f"Failed to retrieve audio: {e}"}

    # Invalid command or missing parameters
    return {"error": "Invalid command or missing required parameters"}


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "audio_files_count": len(audio_files),
        "cached_dates": len(daily_calls_cache)
    }
