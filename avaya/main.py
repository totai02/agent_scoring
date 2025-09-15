import random
import os
import datetime
import hashlib
from fastapi import FastAPI, Query, Response
from fastapi.responses import PlainTextResponse

app = FastAPI()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(SCRIPT_DIR, "audio")
# List all audio files available
audio_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith(".wav")]
# Map call_id -> audio file (giữ cố định)
call_audio_map = {}
# Cache toàn bộ cuộc gọi theo ngày
daily_calls_cache = {}

def get_audio_for_call(call_id: str):
    """Đảm bảo cùng 1 call id trả về cùng 1 file"""
    if call_id not in call_audio_map:
        idx = int(hashlib.md5(call_id.encode()).hexdigest(), 16) % len(audio_files)
        call_audio_map[call_id] = audio_files[idx]
    return os.path.join(AUDIO_DIR, call_audio_map[call_id])

def generate_daily_calls(date: datetime.date):
    """Sinh 10000 call cho 1 ngày cụ thể"""
    if date in daily_calls_cache:
        return daily_calls_cache[date]

    calls = []
    base_datetime = datetime.datetime.combine(date, datetime.time(0, 0, 0))

    seconds_in_day = 24 * 3600
    chosen_seconds = random.sample(range(seconds_in_day), 10000)

    for sec in chosen_seconds:
        ts = base_datetime + datetime.timedelta(seconds=sec)
        call_id = str(random.randint(10**14, 10**15 - 1))

        calls.append({
            "contactid": f"{call_id}_2",
            "startedat": ts,
            "owner": str(random.randint(1000, 9999)),
            "otherparties": f"{random.randint(100000,999999)}, 4603 (agent{random.randint(1000,9999)}.247)",
            "services": f"{random.randint(20000,29999)} (ATC_MASS_VIE_The)",
            "skills": f"{random.randint(20000,29999)} (ATC_MASS_VIETHE)",
            "udfs": "",
            "inums": call_id,
            "agents": f"{random.randint(1000,9999)} (agent{random.randint(1000,9999)}.247)",
            "switchcallid": str(random.randint(10**17, 10**18 - 1))
        })

    daily_calls_cache[date] = calls
    return calls

@app.get("/searchapi")
def searchapi(
    command: str = Query(...),
    layout: str = None,
    param1_startedat: str = None,
    param2_startedat: str = None,
    param3_startedat: str = None,
    param4_startedat: str = None,
    operator_startedat: str = None,
    id: str = None,
):
    if command == "search":
        # Tính datetime range
        start_dt = datetime.datetime.strptime(param1_startedat + " " + param2_startedat, "%d/%m/%y %H:%M:%S")
        end_dt = datetime.datetime.strptime(param3_startedat + " " + param4_startedat, "%d/%m/%y %H:%M:%S")

        results_xml = '<?xml version="1.0" encoding="UTF-8"?><results>'

        current_date = start_dt.date()
        while current_date <= end_dt.date():
            calls = generate_daily_calls(current_date)

            # Lọc theo range thời gian
            for c in calls:
                if start_dt <= c["startedat"] <= end_dt:
                    results_xml += f"""
                    <result contactid="{c['contactid']}">
                        <field name="startedat">{c['startedat'].isoformat()}</field>
                        <field name="owner">{c['owner']}</field>
                        <field name="otherparties">{c['otherparties']}</field>
                        <field name="services">{c['services']}</field>
                        <field name="skills">{c['skills']}</field>
                        <field name="udfs">{c['udfs']}</field>
                        <field name="inums">{c['inums']}</field>
                        <field name="agents">{c['agents']}</field>
                        <field name="switchcallid">{c['switchcallid']}</field>
                    </result>
                    """
            current_date += datetime.timedelta(days=1)

        results_xml += "</results>"
        return PlainTextResponse(content=results_xml, media_type="application/xml")

    elif command == "replay" and id:
        audio_path = get_audio_for_call(id)
        with open(audio_path, "rb") as f:
            data = f.read()
        return Response(content=data, media_type="audio/wav")

    return {"error": "Invalid command or parameters"}
