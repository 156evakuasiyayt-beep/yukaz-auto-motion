# Yük.az — gündəlik Reels avtomatlaşdırması

Hər gün avtomatik olaraq:

```
08:00  GitHub Actions işə düşür
       → bugünkü mövzu seçilir (content/calendar.yaml, 14 mövzu növbə ilə)
       → Claude caption, hashtag, cover başlığı və ekran mətnlərini yazır
       → illüstrasiyalı motion video render olunur (otaq dəsti + gün vaxtı hər gün dəyişir)
       → cover şəkli hazırlanır
       → video + cover + caption 3 Telegram hesabına göndərilir
Siz    → Telegram-da «✅ Paylaş» basırsınız (və ya «❌ Ləğv et»)
09:00  → Instagram Reels + Facebook Page Reels-də paylaşılır, nəticə Telegram-a gəlir
```

### Hər gün yeni dizayn (Atelier rejimi, defolt)
Hər gün AI **30 yaradıcı istiqamətdən birini** götürür (kağız kəsmə, origami, izometrik Bakı, neon gecə, xəritə marşrutu, blueprint…) və OpenMontage-in HyperFrames qaydaları ilə **sıfırdan yeni motion kompozisiya** yazır. Sonra avtomatik keyfiyyət yoxlaması:

1. Texniki yoxlama: `hyperframes lint` + `hyperframes check`
2. 6 kadrdan kontakt vərəqi çəkilir, AI **art-direktor kimi** baxıb 1–10 bal verir
3. Bal 7-dən aşağıdırsa və ya xəta varsa, problemlər AI-a qaytarılır və düzəldilmiş versiya yaradılır (3 cəhdə qədər)
4. Heç biri keçməsə, sabit **"Qutunun səyahəti"** şablonu istifadə olunur (3 otaq × 3 gün vaxtı variantı). Yəni gün heç vaxt boş qalmır.

Telegram mesajında günün dizayn konsepti və keyfiyyət balı göstərilir. Yalnız şablon istifadə etmək üçün repo Variables-da `VIDEO_MODE` = `template` yazın.

AI açarı olmasa və ya xəta versə, mövzunun hazır mətnləri və şablon istifadə olunur, yəni video yenə çıxır.

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
Bot: **t.me/yukaz_reels_bot**. Mesajları və təsdiq düymələrini yalnız `TELEGRAM_CHAT_IDS`-dəki hesablar görür və istifadə edə bilir.
1. Hər üç hesab botu açıb **Start** basmalıdır. Telegram, istifadəçi botu başlatmayınca ona mesaj göndərməyə icazə vermir.
2. Secret-lər: `TELEGRAM_BOT_TOKEN` və `TELEGRAM_CHAT_IDS` = `1265320152,1346490210,8738816943`

### 4. Mətn yazan AI: Claude **və ya** OpenAI
İkisindən biri kifayətdir. Gündə bir qısa sorğu göndərilir, xərci sentlərlədir.
- **Claude:** [console.anthropic.com](https://console.anthropic.com) → API Keys → secret `ANTHROPIC_API_KEY` (model: `claude-opus-5-5`)
- **OpenAI:** [platform.openai.com](https://platform.openai.com/api-keys) → secret `OPENAI_API_KEY` (defolt model: `gpt-5.5`; dəyişmək üçün repo **Variables**-da `OPENAI_MODEL` yaradın)

Hər iki açar varsa, Claude istifadə olunur. OpenAI-ı məcburi seçmək üçün repo → Settings → Secrets and variables → **Variables** → `LLM_PROVIDER` = `openai`.

### 5. GitHub
1. GitHub-da **private** repo yaradın (məs. `yukaz-autopost`) və bu qovluğu push edin.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret** — 6 secret:
   `ANTHROPIC_API_KEY` (və ya `OPENAI_API_KEY`), `META_ACCESS_TOKEN`, `FB_PAGE_ID`, `IG_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`

### 6. İlk sınaq
Repo → **Actions → Daily Reel → Run workflow**. `publish_now` seçsəniz, təsdiqdən sonra 09:00-ı gözləmədən paylaşılır.

---

## Gündəlik istifadə
- Səhər ~08:05-də 3 Telegram hesabına video, cover və caption gəlir.
- **✅ Paylaş:** 3 nəfərdən hər hansı biri basa bilər. Paylaşım 09:00-da olur, 09:00 keçibsə dərhal paylaşılır.
- **❌ Ləğv et:** həmin gün paylaşım olmur.
- 14:00-a qədər heç kim cavab verməsə, həmin gün paylaşılmır və bu barədə mesaj gəlir.
- **Tam avtomatik rejim:** repo → Settings → Secrets and variables → **Variables** → `APPROVAL` = `none`. Kodda dəyişiklik lazım deyil.

## Fərdiləşdirmə
| Nə | Harada |
|---|---|
| Mövzular, hazır mətnlər, brend faktları, telefon | `content/calendar.yaml` |
| Paylaşım saatı | `.github/workflows/daily-reel.yml` → `cron` (UTC) və `--wait-until 09:00` |
| AI-a təlimat (ton, qaydalar) | `autopost/plan.py` → `SYSTEM` |
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
