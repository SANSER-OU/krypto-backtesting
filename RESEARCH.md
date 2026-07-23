# Uuring: kõige robustsema seadistuse otsing

See dokument kirjeldab `research.py` süstemaatilise otsingu metoodikat ja tulemusi —
kuidas jõudsime `config.SCENARIOS`-e viimase kirjeni ("5. Uuringu tulemus
(soovituslik)") ja mida see tulemus tegelikult tõestab (ja mida mitte).

## Metoodika

### Miks järkjärguline otsing, mitte täis-grid?

Meil on kokku ~7 häälestatavat "nuppu" (drop_pct, lookback_periods, rise_pct,
stop_loss_pct, trend_filter_ma, trailing_stop_pct, max_concurrent_positions)
+ 4 lisamehhanismi. Kõigi kombinatsioonide läbiproovimine korraga kasvaks
miljonitesse jooksudesse. Selle asemel lahendasime **etapiviisiliselt**:

1. **Stage A** — riskijuhtimise nupud (192 kombinatsiooni)
2. **Stage B** — signaali nupud, Stage A võitja peal (64 kombinatsiooni)
3. **Stage C** — 4 uut mehhanismi, igaüks eraldi Stage B võitja peal testitud (8 jooksu)
4. **Kombineerimine** — allesjäänud C-mehhanismid koos (1 jooks)
5. **Stage D** — väike lokaalne täpsustus (9 jooksu) + üks-kord-ainult holdout kontroll

**Kokku testitud kombinatsioone: 274** (kõik alla 4 sekundiga, kuna iga
üksik backtest päevaküünaldel on väga kiire).

### Valikureegel (sama kõigis etappides)

Kandidaadid järjestati:
1. **Halvim** kolme tuntud perioodi tootlusest (peamine — turvalisus enne kasumit,
   vastavalt varasemale kokkuleppele)
2. **Keskmine** tootlus kolme perioodi peale (teisene)
3. **Keskmine kasumitegur** (viimane, lahtiharutav kriteerium)

Me EI VALINUD kunagi puhtalt parima juhu ega ainult keskmise järgi — see
oleks täpselt see overfitting-lõks, millest kogu projekti käigus korduvalt
räägitud on.

### Puutumata (holdout) periood

Andmestikku laiendati 2026-01-01-ni (varasem oli 2024-01-01). Uus periood
**2024-2025 ("Puutumata test")** on struktuurselt eraldi hoitud
`config.MARKET_PERIODS`-ist just nimelt selleks, et seda ei saaks kogemata
häälestustsüklisse kaasata. Seda vaadati **ainult üks kord, kõige lõpus**.

## Stage A: riskijuhtimise nupud

Testitud: `trend_filter_ma` × `stop_loss_pct` × `trailing_stop_pct` × `max_concurrent_positions` = 4×4×4×3 = **192 kombinatsiooni**.

**Võitja**: `trend_filter_ma=150`, `stop_loss_pct=None`, `trailing_stop_pct=None`, `max_concurrent_positions=3`
— halvim=0.00%, keskmine=24.27%.

**Oluline tähelepanek**: mitu konfiguratsiooni (MA150/MA200 kombineeritud erinevate stop-loss väärtustega) said IDENTSE tulemuse — kuna trendifilter juba iseseisvalt väldib languseturul kõiki tehinguid, muutuvad paljud teised parameetrid (stop-loss, trailing) selles konkreetses seadistuses "surnud koodiks" (ei mõjuta midagi, kuna vastavaid olukordi lihtsalt ei teki). See ei ole viga, aga tähendab, et Stage A "võitja" ei ole ainuke — mitmed lähedased variandid on matemaatiliselt samaväärsed.

## Stage B: signaali nupud

Testitud Stage A võitja riskiseadete peal: `drop_pct` × `lookback_periods` × `rise_pct` = 4×4×4 = **64 kombinatsiooni**.

**Võitja**: `drop_pct=7.0`, `lookback_periods=7`, `rise_pct=8.0`
— halvim=0.00%, keskmine=31.38%, tõusuturg=+88.66%, sahmerdav=+5.47%.

Lühem vaateaken (7 päeva vs baasjoone 14) ja väiksem languselävi (7% vs 10%) tähendab sagedasemaid, väiksemaid dippe ostetakse — see osutus tuluskamaks kui algne, konservatiivsem seadistus.

## Stage C: uued mehhanismid (igaüks eraldi testitud)

| Mehhanism | Tulemus | Otsus | Põhjendus |
|---|---|---|---|
| **C1: Jahtumisperiood pärast stop-lossi** (3/7/14 küünalt) | Muutuseta (identne baasjoonega kõigil kolmel N väärtusel) | **TAGASI LÜKATUD** | Stage A/B võitjal `stop_loss_pct=None` — see mehhanism reageerib ainult stop-loss sulgemistele, mida siin kunagi ei teki. Mitte "ei tööta", vaid "pole rakendatav" antud baasjoonel. |
| **C2: Osaline kasumivõtt (scale-out 50%)** | keskmine 31.38%→**39.06%**, tõusuturg 88.66%→**116.71%**, halvim jäi 0.00% | **ALLES** | Lukustab poole kasumist kohe ära (rise_pct saavutamisel), ülejäänud pool sõidab trailing-stopiga (lisatud 10%) edasi — parim mõlemast maailmast tõusuturul. Kasumiteguri keskmine LANGES (33.33→11.05), kuna sahmerdaval perioodil tekkis rohkem väiksemaid trade'e. |
| **C3: Ajapõhine sundsulgemine** (30/60/90 küünalt) | 30 ja 60 küünlaga läks **halvim NEGATIIVSEKS** (-0.42% ja -4.62%); 90-ga muutuseta | **TAGASI LÜKATUD** | Sundsulgemine liiga vara lõikab läbi positsioonid, mis oleks hiljem kasumisse pöördunud — sahmerdaval perioodil muutis varasemad head tehingud kahjumiks. |
| **C4: Golden-cross trendifilter** (MA50 > MA200 asemel lihtsa hind>MA200) | **halvim langes 0.00%-lt -43.50%-ni** | **TAGASI LÜKATUD (dramaatiliselt)** | Kahe libiseva keskmise ristumine reageerib trendipöördele AEGLASEMALT kui lihtne "hind > MA" — 2022. aasta krahhi ALGUSES oli MA50 veel korraks MA200-st kõrgemal (2021. aasta tõusu inertsist), mistõttu golden-cross filter LUBAS oste täpselt siis, kui lihtne filter oleks need juba keelanud. **See on kõige olulisem üksik leid**: "tugevama kõlava" filtri lisamine tegi kaitse tegelikult HALVEMAKS, mitte paremaks. |

### Kombineeritud lõplik kandidaat

Ainult C2 (scale-out) parandas baasjoont, seega lõplik kombinatsioon = Stage B võitja + scale-out 50% + trailing_stop_pct=10 (scale-out'i eelduseks): **halvim=0.00%, keskmine=39.06%**.

## Stage D: lokaalne täpsustus + holdout valideerimine

9 väikest varianti (drop_pct ja rise_pct ±2 punkti ümber lõpliku kandidaadi) ei parandanud tulemust — jäime eelmise valiku juurde.

### Lõplik valitud konfiguratsioon

```python
StrategyConfig(
    drop_pct=7.0, lookback_periods=7, rise_pct=8.0,
    trend_filter_ma=150, trailing_stop_pct=10.0, scale_out_fraction=0.5,
)
BacktestConfig(starting_capital=10_000.0, max_concurrent_positions=3, fee_rate=0.001)
```

### Tulemused kõigil neljal perioodil

| Periood | Tootlus | PF | Tehinguid | Max DD |
|---|---|---|---|---|
| Tõusuturg (2020-2021) | **+116.71%** | 31.96 | 30 | 14.03% |
| Languseturg (2022) | **0.00%** | 0.00 | 0 | 0.00% |
| Külgsuunaline (2023) | **+0.46%** | 1.20 | 4 | 10.00% |
| **Puutumata (2024-2025)** | **+42.23%** ($4,223) | 2.68 | 31 | **18.24%** |

Tuntud perioodide keskmine: +39.06%. Puutumata perioodi tulemus: +42.23%.
**Vahe: -3.17 protsendipunkti** (miinusmärk tähendab, et holdout tegelikult
*ületas* tuntud perioodide keskmist).

### Ausalt, mida see tõestab — ja mida mitte

**Julgustav märk**: puutumata periood ei olnud halvem kui tuntud perioodide
keskmine — kui strateegia oleks olnud üle-häälestatud (overfitted) täpselt
neile 3 varasemale perioodile, ootaksime holdout'il märgatavalt HALVEMAT
tulemust. Seda ei juhtunud.

**Aga ÄRA loe sellest liigset kindlust**:
- **Max drawdown holdout'il (18.24%) oli suurem** kui ükski kolmest
  tuntud perioodist (parim neist oli 14.03%). Lõpp-punkti tootlus nägi hea
  välja, aga tee sinnani oli karmim, kui varasemad testid näitasid — see
  on täpselt see risk, mida pelgalt tootluse number varjab.
- 2024-2025 oli BTC jaoks samuti üldiselt soodne periood (mitte tõeline
  "teist tüüpi" turg, mida me pole varem näinud) — holdout'i hea tulemus
  ei tähenda, et strateegia toimiks sama hästi näiteks järgmises
  mitmeaastases languses.
- See on jätkuvalt **ainult BTC/USDT**, ainult **päevaküünaldel**, ainult
  ~6 aasta ajaloolistel andmetel. Reaalne täitmine (libisemine, hinnavahemik
  küünla sees) oleks tulemust veidi halvendanud — seda simulatsioon ei arvesta.
- Stage A/B/C otsingu käigus nägime, et mitmed "tugevama kõlava" idee
  (golden-cross, ajapõhine sundsulgemine, portfelli-katkestaja varasemast
  vestlusest) tegelikult HALVENDASID tulemust — see peaks tekitama üldist
  ettevaatlikkust iga uue "täiendava kaitse" idee suhtes: intuitsioon
  finantsstrateegiates sageli eksib, ainult mõõtmine annab vastuse.
- See on endiselt ainult **backtest** — järgmine samm on **paper trading**
  (fiktiivse rahaga, päris turul, päris ajas), mitte otse päris raha.

## Kokkuvõte

274 testitud kombinatsiooni viisid ühe, ausalt valideeritud, seni
robustseima seadistuseni (`config.SCENARIOS[5]`), mis on nüüd projekti
alaline osa koos kõigi varasemate õppestsenaariumidega (0-4). Kõige
väärtuslikum tulemus pole aga number, vaid meetod ise: **golden-cross
leid** (tugevam filter = halvem kaitse) on konkreetne, mõõdetud näide
sellest, miks tuleb iga ideed testida, mitte lihtsalt "loogilisena" tunduva
põhjal kasutusele võtta.
