import asyncio,json,logging,os,secrets,sys,tempfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from vercel.blob import AsyncBlobClient
log=logging.getLogger(__name__)
async def read_db():
 v=await AsyncBlobClient().get("state/anonim_bot.db",access="private")
 if v is None:return None
 if v.status_code!=200 or v.stream is None:raise RuntimeError("Read failure")
 return b"".join([x async for x in v.stream])
async def write_db(data):
 await AsyncBlobClient().put("state/anonim_bot.db",data,access="private",overwrite=True,add_random_suffix=False,content_type="application/octet-stream")
class handler(BaseHTTPRequestHandler):
 def respond(self,code,result):
  raw=json.dumps(result).encode()
  self.send_response(code)
  self.send_header("Content-Type","application/json")
  self.send_header("Content-Length",str(len(raw)))
  self.end_headers()
  self.wfile.write(raw)
 def do_GET(self):
  if self.path.split("?")[0]=="/api/setup":
   try:
    import anonim_bot as bot
    host=self.headers.get("Host","")
    if not host.endswith(".vercel.app"):return self.respond(403,{"error":"invalid_host"})
    ok=bot.tg_request("setWebhook",{"url":"https://"+host+"/api/webhook","secret_token":os.environ["TELEGRAM_WEBHOOK_SECRET"],"max_connections":1,"allowed_updates":["message","callback_query"]})
    return self.respond(200 if ok else 503,{"configured":bool(ok)})
   except Exception:
    log.exception("setup");return self.respond(500,{"error":"setup_failed"})
  return self.respond(200,{"service":"anonim-telegram-bot","online":True})
 def do_POST(self):
  if self.path.split("?")[0]!="/api/webhook":return self.respond(404,{"error":"not_found"})
  secret=os.getenv("TELEGRAM_WEBHOOK_SECRET","")
  if not secret or not secrets.compare_digest(self.headers.get("X-Telegram-Bot-Api-Secret-Token",""),secret):return self.respond(403,{"error":"forbidden"})
  try:
   n=int(self.headers.get("Content-Length","0"))
   if n<=0 or n>1048576:return self.respond(413,{"error":"too_large"})
   u=json.loads(self.rfile.read(n))
   with tempfile.TemporaryDirectory() as d:
    dbfile=Path(d)/"anonim_bot.db"
    old=asyncio.run(read_db())
    if old is not None:dbfile.write_bytes(old)
    os.environ["DB_PATH"]=str(dbfile)
    import anonim_bot as bot
    bot.db=bot.Database(str(dbfile))
    me=bot.tg_request("getMe")
    if not me:raise RuntimeError("getMe failure")
    if "message" in u:bot.handle_message(u["message"],me["username"])
    elif "callback_query" in u:bot.handle_callback(u["callback_query"],me["username"])
    asyncio.run(write_db(dbfile.read_bytes()))
   return self.respond(200,{"ok":True})
  except Exception:
   log.exception("update failure");return self.respond(500,{"error":"update_failed"})
