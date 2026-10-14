# Yük.az — gündəlik Reels avtomatlaşdırması

Hər gün avtomatik olaraq:

```
08:00  GitHub Actions işə düşür
       → bugünkü mövzu seçilir (content/calendar.yaml, 14 mövzu növbə ilə)
       → Claude caption, hashtag, cover başlığı və ekran mətnlərini yazır
       → illüstrasiyalı motion video render olunur (otaq dəsti + gün vaxtı hər gün dəyişir)
       → cover şəkli hazırlanır
       → video + caption Telegram-a sizə göndərilir
Siz    → GitHub-da «Approve» basırsınız
09:00  → Instagram Reels + Facebook Page Reels-də paylaşılır, nəticə Telegram-a gəlir
```

Videoların müxtəlifliyi: 3 otaq dəsti (ev / ofis / məişət texnikası) × 3 gün vaxtı (səhər / gün batımı / gecə) × 14 mövzu × 5 musiqi tonu. Claude cavab verməsə, mövzunun hazır mətnləri istifadə olunur, yəni video yenə çıxır.

---

## Quraşdırma (bir dəfəlik)

### 1. Instagram və Facebook hazırlığı
1. Instagram hesabı **Professional (Business)** olmalıdır: Instagram → Settings → Account type.
2. Instagram hesabı Yük.az **Facebook səhifəsinə bağlı** olmalıdır: [Meta Business Suite](https://business.facebook.com) → Settings → Accounts → Instagram accounts.

### 2. Meta App və daimi token
1. [developers.facebook.com](https://developers.facebook.com/apps) → **Create App** → tip: **Business** → Yük.az biznes portfelini seçin.
2. App-a **Instagram** (Instagram API with Facebook Login) və **Facebook Login for Business** məhsullarını əlavə edin.
3. [Business Settings](https://business.facebook.com/settings) → **Users → System users** → **Add** (rol: Admin).
4. Həmin system user üçün **Assign assets**:
   - Facebook səhifəsi: **Full control**
   - Instagram hesabı: **Full control**
   - App: **Manage app**
5. System user → **Generate new token** → App-ı seçin → **Expiration: Never** → icazələr:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management`
6. Alınan token ilə bu əmri işlədin. O, `FB_PAGE_ID`, `IG_USER_ID` və daimi **Page token**-i (`META_ACCESS_TOKEN`) çap edəcək:
   ```
   python -m autopost.setup_helper meta <SYSTEM_USER_TOKEN>
   ```

> App «Development» rejimində qala bilər: öz biznesinizin səhifə və Instagram hesabına paylaşmaq üçün App Review lazım deyil.

### 3. Telegram bot (təsdiq və bildirişlər)
1. Telegram-da [@BotFather](https://t.me/BotFather) → `/newbot` → token-i saxlayın (`TELEGRAM_BOT_TOKEN`).
2. Yeni botunuza `/start` yazın.
3. `python -m autopost.setup_helper telegram <BOT_TOKEN>` → `TELEGRAM_CHAT_ID` çap olunur.

### 4. Claude API açarı
[console.anthropic.com](https://console.anthropic.com) → API Keys → `ANTHROPIC_API_KEY`. Model: `claude-opus-5-5`. Gündə bir qısa sorğu göndərilir, xərci sentlərlədir.

### 5. GitHub
1. GitHub-da **private** repo yaradın (məs. `yukaz-autopost`) və bu qovluğu push edin.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret** — 6 secret:
   `ANTHROPIC_API_KEY`, `META_ACCESS_TOKEN`, `FB_PAGE_ID`, `IG_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
3. Repo → **Settings → Environments → New environment** → ad: `production` → **Required reviewers**: özünüzü əlavə edin.
4. Telefonunuza **GitHub** tətbiqini qurun, təsdiq bildirişləri ora da gələcək.

### 6. İlk sınaq
Repo → **Actions → Daily Reel → Run workflow**. `publish_now` seçsəniz, təsdiqdən sonra 09:00-ı gözləmədən paylaşılır.

---

## Gündəlik istifadə
- Səhər Telegram-a video, cover və caption gəlir.
- Bəyənirsinizsə: mesajdakı linkdən → **Review deployments** → `production` → **Approve**.
- Bəyənmirsinizsə: **Reject** basın, həmin gün paylaşım olmur.
- **Tam avtomatik rejim:** Settings → Environments → `production` → Required reviewers-i silin. Kodda dəyişiklik lazım deyil.

## Fərdiləşdirmə
| Nə | Harada |
|---|---|
| Mövzular, hazır mətnlər, brend faktları, telefon | `content/calendar.yaml` |
| Paylaşım saatı | `.github/workflows/daily-reel.yml` → `cron` (UTC) və `--wait-until 09:00` |
| Claude-a təlimat (ton, qaydalar) | `autopost/plan.py` → `SYSTEM` |
| Otaq dəstləri, əşyalar, rəng palitraları | `autopost/scenes.py` |
| Animasiya və səhnələr | `template/index.html` |

## Lokal işlətmə
```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m autopost.build --out out                    # video + cover + caption
python -m autopost.publish --out out --dry-run        # nə paylaşılacağını göstərir
```
Tələblər: Python 3.12, Node.js 22+, FFmpeg.

## Məhdudiyyətlər
- Meta API sutkada 30-dan çox paylaşıma icazə vermir (bizdə gündə 1 paylaşım olur).
- Facebook Reels üçün xüsusi cover qoyma "best effort" rejimindədir: alınmasa, video yenə paylaşılır.
- GitHub cron bəzən 5–15 dəqiqə gecikə bilər. Ona görə video 08:00-da hazırlanır və paylaşım 09:00-dadır.

## TikTok (2-ci mərhələ)
TikTok-un Content Posting API-si ilə videonu birbaşa açıq paylaşmaq üçün TikTok tətbiqinin auditdən keçməsi lazımdır. Audit olana qədər video TikTok-a **qaralama (inbox)** kimi göndəriləcək və tətbiqdə bir toxunuşla paylaşılacaq. Bunun üçün [developers.tiktok.com](https://developers.tiktok.com)-da app yaradıb `video.upload` icazəsini almaq lazımdır.
