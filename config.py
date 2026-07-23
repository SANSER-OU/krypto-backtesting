"""
Kõik strateegia ja simulatsiooni parameetrid ühest kohast.
Muuda siin väärtusi, et katsetada erinevate seadistustega — koodi ennast
mujal muutma ei pea.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyConfig:
    # Osta, kui hind on langenud vähemalt X% viimase Y küünla kõrgeimast hinnast.
    drop_pct: float = 10.0       # X
    lookback_periods: int = 14   # Y

    # Müü konkreetne positsioon, kui hind on tõusnud Z% selle positsiooni
    # enda ostuhinnast.
    rise_pct: float = 8.0        # Z

    # Valikuline turvapiir: kui hind langeb ostuhinnast rohkem kui
    # stop_loss_pct, müü positsioon kahjumiga maha (kaitse "langeva noa"
    # vastu). Vaikimisi väljas (None) — kasutaja kirjeldatud strateegial
    # seda algselt ei olnud.
    stop_loss_pct: float | None = None

    # Valikuline trendifilter: osta ainult siis, kui hind on üleval pool
    # N-päevast libisevat keskmist (nt 200) — st väldi "languse" ostmist,
    # kui pikaajaline trend on tervikuna langev. Vaikimisi väljas (None).
    trend_filter_ma: int | None = None

    # Valikuline "golden cross" trendifilter: kui seatud KOOS trend_filter_ma-ga,
    # nõuab ostuks, et lühem libisev keskmine (nt MA50) oleks pikemast
    # (trend_filter_ma, nt MA200) kõrgemal — tugevam/erinev trendisignaal kui
    # lihtne "hind > MA200". Vaikimisi väljas (None).
    trend_filter_fast_ma: int | None = None

    # Valikuline trailing-exit: kui seatud, ei müüda positsiooni enam kohe
    # rise_pct% tõusul, vaid alles siis, kui hind on rise_pct% võrra
    # ostuhinnast tõusnud ("relvastumine") JA seejärel langenud
    # trailing_stop_pct% võrra oma tipust (peak) alates relvastumisest —
    # see laseb tugevatel tõusudel kauem kasvada. Vaikimisi väljas (None),
    # mille korral kehtib algne fikseeritud rise_pct müügiloogika.
    trailing_stop_pct: float | None = None

    # Valikuline "jahtumisperiood" pärast stop-lossi: pärast iga stop-loss
    # sulgemist blokeeritakse uued ostusignaalid järgmise N küünla jooksul.
    # Väldib "whipsaw" mustrit (kohe uuesti ostmine samasse langusesse, mis
    # just stop-lossi käivitas). Vaikimisi väljas (None).
    cooldown_after_stop_loss: int | None = None

    # Valikuline osaline kasumivõtt ("scale-out"): kui rise_pct sihtmärk
    # esimest korda saavutatakse, müüakse ainult see osa positsioonist
    # (nt 0.5 = pool), ülejäänu jääb edasi kasvama trailing_stop_pct loogika
    # järgi. Nõuab, et trailing_stop_pct oleks samuti seatud — muidu pole
    # "ülejäänud poolel" mõtet, kuna see müüdaks niigi kohe täies mahus ära.
    # Vaikimisi väljas (None).
    scale_out_fraction: float | None = None

    # Valikuline ajapõhine sundsulgemine: kui positsioon on olnud avatud
    # rohkem kui N küünalt, suletakse see hinnast sõltumata — väldib kapitali
    # lõputut "kinnijäämist" ootama sihtmärki, mis ei pruugi kunagi tulla.
    # Vaikimisi väljas (None).
    max_holding_periods: int | None = None


@dataclass(frozen=True)
class BacktestConfig:
    starting_capital: float = 10_000.0
    max_concurrent_positions: int = 5
    fee_rate: float = 0.001  # 0.1% Binance spot-kauplemise vaikemäär

    # Valikuline portfelli-tasandi "katkestaja": kui KOGU portfelli väärtus on
    # juba langenud rohkem kui max_portfolio_drawdown_pct% oma senisest tipust,
    # ei avata uusi positsioone (olemasolevaid hallatakse endiselt tavapäraselt),
    # kuni portfell on taas taastunud selle piiri seest välja. Vaikimisi väljas.
    max_portfolio_drawdown_pct: float | None = None

    @property
    def slot_size(self) -> float:
        """Iga üksiku positsiooni suurus (kapital jagatud pesade vahel)."""
        return self.starting_capital / self.max_concurrent_positions


@dataclass(frozen=True)
class DataConfig:
    symbol: str = "BTCUSDT"
    interval: str = "1d"  # Binance kline intervall: 1d, 4h, 1h, ...
    fetch_start: str = "2020-01-01"
    fetch_end: str = "2026-01-01"
    cache_dir: str = "data"


@dataclass(frozen=True)
class MarketPeriod:
    name: str
    start: str
    end: str


# Kolm reaalset BTC turuperioodi, mida kõiki sama andmestiku pealt testitakse.
# ~30-päevane puhver enne iga perioodi algust tagab, et rolling-high on
# perioodi esimesel päeval juba täisandmetega arvutatud.
MARKET_PERIODS = [
    MarketPeriod("Tõusuturg (2020-2021)", "2020-10-01", "2021-04-15"),
    MarketPeriod("Languseturg (2022)", "2022-01-01", "2022-12-31"),
    MarketPeriod("Külgsuunaline turg (2023)", "2023-04-01", "2023-10-15"),
]

# PUUTUMATA (holdout) periood — seda EI TOHI kunagi kasutada parameetrite
# valimiseks/häälestamiseks, ainult lõpliku valiku ausaks kontrolliks
# PÄRAST kõiki otsuseid (vt research.py Stage D). Hoitud MARKET_PERIODS-ist
# eraldi, et ei saaks kogemata häälestustsüklisse sattuda.
HOLDOUT_PERIOD = MarketPeriod("Puutumata test (2024-2025)", "2024-01-01", "2025-12-31")

# 210 päeva puhver katab ka valikulise 200-päevase trendifiltri (MA200) +
# lookback_periods soojenduse, isegi kui konkreetne stsenaarium seda ei kasuta.
WARMUP_DAYS = 210

STRATEGY = StrategyConfig()
BACKTEST = BacktestConfig()
DATA = DataConfig()


@dataclass(frozen=True)
class Scenario:
    name: str
    strategy: StrategyConfig
    backtest: BacktestConfig = BACKTEST


# Kumulatiivsed parandusstsenaariumid: iga järgmine lisab eelmisele juurde
# ühe muudatuse, et oleks selge, mis TÄPSELT mida mõjutab.
SCENARIOS: list[Scenario] = [
    Scenario("0. Baasjoon (praegune)", STRATEGY),
    Scenario(
        "1. + Stop-loss (-15%)",
        StrategyConfig(
            drop_pct=STRATEGY.drop_pct,
            lookback_periods=STRATEGY.lookback_periods,
            rise_pct=STRATEGY.rise_pct,
            stop_loss_pct=15.0,
        ),
    ),
    Scenario(
        "2. + Trendifilter (MA200)",
        StrategyConfig(
            drop_pct=STRATEGY.drop_pct,
            lookback_periods=STRATEGY.lookback_periods,
            rise_pct=STRATEGY.rise_pct,
            stop_loss_pct=15.0,
            trend_filter_ma=200,
        ),
    ),
    Scenario(
        "3. + Trailing exit (-10% tipust)",
        StrategyConfig(
            drop_pct=STRATEGY.drop_pct,
            lookback_periods=STRATEGY.lookback_periods,
            rise_pct=STRATEGY.rise_pct,
            stop_loss_pct=15.0,
            trend_filter_ma=200,
            trailing_stop_pct=10.0,
        ),
    ),
    Scenario(
        "4. + Rohkem positsioone tõusutrendis (max 8)",
        strategy=StrategyConfig(
            drop_pct=STRATEGY.drop_pct,
            lookback_periods=STRATEGY.lookback_periods,
            rise_pct=STRATEGY.rise_pct,
            stop_loss_pct=15.0,
            trend_filter_ma=200,
            trailing_stop_pct=10.0,
        ),
        # max_concurrent_positions 5 -> 8: rohkem "padruneid" dippide ostmiseks,
        # AGA trend_filter_ma=200 ülal kehtib jätkuvalt kõigi positsioonide
        # (ka nende 6.-8.) kohta — languses turus ei osteta ikka mitte kunagi juurde,
        # ainult tugeva tõusutrendi SEES olevate dippide peal.
        backtest=BacktestConfig(
            starting_capital=BACKTEST.starting_capital,
            max_concurrent_positions=8,
            fee_rate=BACKTEST.fee_rate,
        ),
    ),
    Scenario(
        # research.py staged otsingu (Stage A-D) tulemus: vt RESEARCH.md.
        # Halvim tuntud periood = 0.00% (bear jätkuvalt trendifiltriga täielikult
        # välditud), keskmine tuntud tootlus +39.06%, puutumata (2024-2025)
        # periood +42.23% — ei näidanud overfitting'u märke (holdout oli isegi
        # veidi parem kui tuntud perioodide keskmine).
        "5. Uuringu tulemus (soovituslik)",
        strategy=StrategyConfig(
            drop_pct=7.0,
            lookback_periods=7,
            rise_pct=8.0,
            trend_filter_ma=150,
            trailing_stop_pct=10.0,
            scale_out_fraction=0.5,
        ),
        backtest=BacktestConfig(
            starting_capital=BACKTEST.starting_capital,
            max_concurrent_positions=3,
            fee_rate=BACKTEST.fee_rate,
        ),
    ),
]
