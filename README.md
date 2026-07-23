# Krüpto backtesting tööriist

Tööriist "osta languses, müü tõusus" tüüpi kauplemisstrateegia testimiseks
BTC/USDT ajaloolistel hinnaandmetel. **See EI kaupleb päris rahaga** — see
on esimene samm kolmest:

1. **Backtesting** (see tööriist) — kas strateegia üldse töötab minevikus?
2. Paper trading — fiktiivse rahaga, päris turul, päris ajas.
3. Alles siis väike päris raha.

## Seadistamine

```bash
cd /Users/maitsander/E-os
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Käivitamine

```bash
python main.py
```

Esimesel käivitusel laeb skript BTC/USDT päevaküünlad Binance avalikust
API-st (2020-01-01 kuni 2024-01-01) ja salvestab need `data/` kausta —
järgmised käivitused kasutavad juba salvestatud andmeid.

## Kuidas andmed töötavad

Binance API (`GET /api/v3/klines`) tagastab avalikke turuandmeid ilma
kontota ja API-võtmeta — need on samad hinnad, mida näeb igaüks Binance'i
graafikult. Iga "küünal" (candle) sisaldab **OHLCV** väärtusi ühe perioodi
(siin: üks päev) kohta:

- **Open** — hind perioodi alguses
- **High** — kõrgeim hind perioodi jooksul
- **Low** — madalaim hind perioodi jooksul
- **Close** — hind perioodi lõpus
- **Volume** — kui palju BTC-d selle perioodi jooksul kaubeldi

Binance tagastab korraga max 1000 küünalt, seega mitme aasta andmete
jaoks teeb `data_fetch.py` mitu päringut järjest ("pagination").

## Strateegia loogika

Kõik parameetrid on failis **`config.py`** — muuda seal, mitte mujal koodis:

- `drop_pct` (X) — osta, kui hind on langenud vähemalt X% viimase Y küünla
  kõrgeimast hinnast.
- `lookback_periods` (Y) — mitme küünla kõrgeimat hinda vaadatakse.
- `rise_pct` (Z) — müü konkreetne positsioon, kui hind on tõusnud Z%
  SELLE POSITSIOONI enda ostuhinnast.
- `stop_loss_pct` — **valikuline turvapiir, vaikimisi väljas (`None`)**.
  Kui sead nt `stop_loss_pct = 15.0`, müüakse positsioon automaatselt
  kahjumiga maha, kui hind langeb 15% alla ostuhinna — kaitse selle vastu,
  et hind lihtsalt jätkab langust lõputult ("langeva noa püüdmine").
  **Soovitan seda katsetada ja tulemusi ilma stop-lossita võrrelda.**
- `max_concurrent_positions` — mitu positsiooni tohib korraga lahti olla
  (pyramiding). Kapital jagatakse selle arvu vahel võrdseteks "pesadeks".

## Kolm testitavat turuperioodi

| Periood | Vahemik | Iseloom |
|---|---|---|
| Tõusuturg | 2020-10-01 – 2021-04-15 | BTC ~$10.8k → ~$64k |
| Languseturg | 2022-01-01 – 2022-12-31 | BTC ~$47k → ~$16.5k (LUNA, FTX) |
| Külgsuunaline | 2023-04-01 – 2023-10-15 | BTC kõikus ~$25k–$31k |

Iga periood testitakse eraldi samade parameetritega, et näha, kus
strateegia töötab ja kus mitte — üksik hea tulemus ühel perioodil ei
tähenda midagi.

## Osta-ja-hoia võrdlus

Iga perioodi kohta näidatakse ka, mis oleks tulemus, kui samale summale
oleks lihtsalt perioodi alguses BTC ostetud ja hoitud lõpuni, ilma ühegi
täiendava tehinguta — see on passiivse indeksinvesteerimise (nt
BlackRock/Vanguard indeksifondide) filosoofia. Kui aktiivne strateegia ei
suuda seda lihtsat lähenemist ületada, on põhjust kahelda, kas kogu
keerukus on väärt vaeva.

## Olulised hoiatused

- **Overfitting**: ära häälesta X/Y/Z parameetreid, kuni need nende 3
  perioodi peal heaks lähevad — see pole valideerimine, vaid mineviku
  meelde jätmine. Vajalik oleks eraldi "puutumata" test-periood.
- **Tasud**: ~0.1% tehingu kohta (~0.2% ringiga) võib sagedaste tehingute
  korral reaalselt suure osa kasumist ära süüa — raport näitab seda numbrina.
- **Stop-loss on vaikimisi väljas** — ilma selleta ei kaitse strateegia
  sind pikaajalise languse eest.
- **Täitmise lihtsustus**: simulatsioon eeldab täitmist täpselt küünla
  sulgemishinnaga — reaalsuses (libisemine) oleks tulemus veidi halvem.
- **3 perioodi on õppimise miinimum**, mitte lõplik tõestus.

## Uuring: kõige robustsema seadistuse otsing

`python research.py` käivitab süstemaatilise järkjärgulise otsingu (274
kombinatsiooni), mis leidis `config.SCENARIOS`-e 6. kirje ("Uuringu tulemus,
soovituslik") ja valideeris selle puutumata 2024-2025 perioodil. Vt
**RESEARCH.md** täieliku metoodika, tulemuste ja ausate piirangute jaoks.

## Testid

```bash
pytest
```

Kontrollivad, et rolling-high/signaali arvutus ei kasuta kunagi tulevasi
andmeid ("lookahead bias") ning et tasude ja max drawdown'i arvutus on
matemaatiliselt korrektne.
