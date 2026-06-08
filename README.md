# 🤖 Funstat Bot

Telegram foydalanuvchilarini tahlil qiluvchi bot (Funstat analogu).

## 📁 Loyiha tuzilmasi

```
funstat_bot/
├── main.py                          # Asosiy ishga tushirish
├── requirements.txt                 # Kutubxonalar
├── .env.example                     # Config namunasi
├── Dockerfile                       # Docker
├── docker-compose.yml               # PostgreSQL + Redis + Bot
├── bot/
│   ├── handlers.py                  # Foydalanuvchi buyruqlari
│   └── admin.py                     # Admin buyruqlari
├── collector/
│   └── telegram_collector.py        # Telethon ma'lumot yig'uvchi
├── database/
│   └── models.py                    # SQLAlchemy modellari
└── config/
```

## ⚙️ O'rnatish

### 1. Kerakli tokenlarni oling
- **Bot token** → [@BotFather](https://t.me/BotFather)
- **API ID & Hash** → [my.telegram.org](https://my.telegram.org)

### 2. .env faylini sozlang
```bash
cp .env.example .env
# .env faylini tahrirlang
```

### 3. Docker bilan ishga tushirish (tavsiya)
```bash
docker-compose up -d
```

### 4. Oddiy ishga tushirish
```bash
pip install -r requirements.txt
python main.py
```

## 🔧 Buyruqlar

### Foydalanuvchilar uchun
| Buyruq | Tavsif |
|--------|--------|
| /start | Bosh menyu |
| /search @username | Foydalanuvchi qidirish |
| /track @username | Kuzatishni boshlash |
| /stats | Baza statistikasi |
| /credits | Kredit holati |

### Adminlar uchun
| Buyruq | Tavsif |
|--------|--------|
| /admin | Admin panel |
| /scan @guruh | Guruhni skanerlash |
| /ban user_id | Foydalanuvchini bloklash |
| /addcredits user_id N | Kredit qo'shish |

## 🗄️ Ma'lumotlar bazasi

- **TelegramUser** — yig'ilgan TG foydalanuvchilar
- **NameHistory** — ism/username o'zgarishlari tarixi
- **TelegramGroup** — guruh va kanallar
- **GroupMembership** — kim qaysi guruhda
- **UserMessage** — ommaviy xabarlar
- **BotUser** — bot foydalanuvchilari
- **TrackedUser** — kuzatilayotganlar

## ⚠️ Muhim eslatma

Bu bot faqat **ommaviy** Telegram ma'lumotlari bilan ishlaydi.
Shaxsiy yozishmalar, telefon raqamlar yoki maxfiy ma'lumotlar
saqlanmaydi. Faqat qonuniy maqsadlarda foydalaning.
