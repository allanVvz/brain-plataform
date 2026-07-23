"""Seed the complete Baita cardapio product tree and category cover assets.

This is the definitive catalog fixture for the public Baita menu app:
category/entity/product nodes live in AI-BRAIN, category covers are graph
connections to approved Gallery assets, and the public /api/menu endpoint
resolves covers from those graph edges at request time.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = API_DIR.parent
for path in (API_DIR, ROOT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from utils.tls import configure_trust_store

configure_trust_store()

from services import supabase_client
from scripts.seed_baita_cardapio_assets import (
    CARDAPIO_CAMPAIGN_SLUG,
    SEED_SOURCE,
    _create_asset_row,
    _edge,
    _ensure_asset_node,
    _find_image,
)

FULL_MENU_SOURCE = "baita_full_menu_seed"

CATEGORY_SPECS = [
    {"slug": "cervejas", "title": "Cervejas", "eyebrow": "GELADAS", "cover_aliases": ["lagunitas-daytime", "cervejas-premium"], "position": 10},
    {"slug": "600ml-e-litro", "title": "600ml e Litro", "eyebrow": "PRA DIVIDIR", "cover_aliases": ["patagonia-daytime", "cervejas-premium"], "position": 20},
    {"slug": "bebidas-em-lata", "title": "Bebidas em Lata", "eyebrow": "READY TO DRINK", "cover_aliases": ["editorial-product-bg"], "position": 30},
    {"slug": "energeticos", "title": "Energeticos", "eyebrow": "ENERGIA", "cover_aliases": ["editorial-product-bg-2"], "position": 40},
    {"slug": "refrigerantes-sucos-chas", "title": "Refrigerantes / Sucos / Chas", "eyebrow": "SEM ALCOOL", "cover_aliases": ["baita-conveniencia-brand"], "position": 50},
    {"slug": "isotonicos", "title": "Isotonicos", "eyebrow": "HIDRATA", "cover_aliases": ["baita-logo"], "position": 60},
    {"slug": "destilados", "title": "Destilados", "eyebrow": "GARRAFAS", "cover_aliases": ["yergermeter", "jagermeister"], "position": 70},
    {"slug": "espumantes-e-vinhos", "title": "Espumantes e Vinhos", "eyebrow": "BRINDE", "cover_aliases": ["suspeito", "vinhos-espumantes"], "position": 80},
    {"slug": "bomboniere", "title": "Bomboniere", "eyebrow": "DOCES", "cover_aliases": ["baita-estrelas", "2estrelhas"], "position": 90},
    {"slug": "comidas", "title": "Comidas", "eyebrow": "BATEU FOME", "cover_aliases": ["editorial-product-bg-2"], "position": 100},
    {"slug": "salgadinhos", "title": "Salgadinhos", "eyebrow": "MUNCHIES", "cover_aliases": ["baita-conveniencia-brand"], "position": 110},
    {"slug": "cigarro", "title": "Cigarro", "eyebrow": "TABELADO", "cover_aliases": ["baita-logo"], "position": 120},
    {"slug": "filtros-e-piteiras", "title": "Filtros e Piteiras", "eyebrow": "HEADSHOP", "cover_aliases": ["baita-asset-2estrelhas"], "position": 130},
    {"slug": "sedas", "title": "Sedas", "eyebrow": "ROLLING", "cover_aliases": ["baita-logo"], "position": 140},
    {"slug": "tabaco", "title": "Tabaco", "eyebrow": "TABACARIA", "cover_aliases": ["baita-conveniencia-brand"], "position": 150},
]

HEADER_TO_SLUG = {spec["title"].upper(): spec["slug"] for spec in CATEGORY_SPECS}
HEADER_TO_SLUG.update({
    "CERVEJAS": "cervejas",
    "600ML E LITRO": "600ml-e-litro",
    "BEBIDAS EM LATA": "bebidas-em-lata",
    "ENERGETICOS": "energeticos",
    "ENERGÉTICOS": "energeticos",
    "REFRIGERANTES / SUCOS / CHAS": "refrigerantes-sucos-chas",
    "REFRIGERANTES / SUCOS / CHÁS": "refrigerantes-sucos-chas",
    "ISOTONICOS": "isotonicos",
    "DESTILADOS": "destilados",
    "ESPUMANTES E VINHOS": "espumantes-e-vinhos",
    "BOMBONIERE": "bomboniere",
    "COMIDAS": "comidas",
    "SALGADINHOS": "salgadinhos",
    "FILTROS E PITEIRAS": "filtros-e-piteiras",
    "SEDAS": "sedas",
    "TABACO": "tabaco",
})

SPECIAL_SLUGS = {
    "LAGUNITAS DAY TIME 355ML": "lagunitas-daytime-355ml",
    "PATAGONIA WEISSE LATA 473ML": "patagonia-weisse-473ml",
    "LICOR JAGERMEISTER 700ML": "licor-jagermeister-700ml",
    "VINHO SUSPEITO BRANCO / ESPUMANTE BRUT / MERLOT ROSE 750ML": "vinho-suspeito-750ml",
}

MENU_TEXT = r"""
CERVEJAS
AMSTEL LATA 473 ML - 9
CORONA ZERO 330ML - 13
AMSTEL LONG 355ML - 9
AMSTEL ULTRA 275ML - 9
BLUE MOON LONG NECK 355ML - 19
BRAHMA CHOPP 473ML - 9
BUDWEISER LATA 473ML - 8
BUDWEISER LONG 330ML - 10
CERVEJA IMIGRACAO LAGER ZERO CARBO 355ML - 10
CORONA LATA 473ML - 12
CORONA LONG NECK 330ML - 13
EISENBAHN PILSEN 355ML - 9
ESTRELLA GALICIA 355ML - 12
ESTRELLA GALICIA 473ml - 8,5
FLYING FISH 330 ML - 10
GOOSE ISLAND SESSION IPA 355ML - 17
HEINEKEN 600ML - 19
HEINEKEN LATA 473ML - 11
HEINEKEN LONG NECK 330ML - 12
HEINEKEN ZERO LONG NECK 330ML - 12
HOCUS POCUS ALMA 350ML - 15
HOCUS POCUS ORANGE SUNSHINE 350ML - 15
IMIGRACAO LAGER GREMIO 473ML - 8
IMIGRACAO LAGER INTER 473ML - 8
LAGUNITAS DAY TIME 355ML - 20
MICHELOB LONG NECK 330ML - 11
ORIGINAL LATAO 473ML - 10
PATAGONIA AMBER LATA 473ML - 13
PATAGONIA IPA 355ML - 13
PATAGONIA IPA LATA 473ML - 13
PATAGONIA WEISSE LATA 473ML - 13
ROLETA RUSSA APA 355ML - 12
ROLETA RUSSA EASY IPA LONGNECK 355 ML - 10
SCHIN PILSEN 473ML - 5,5
SOL PREMIUM LONG NECK 330ML - 9
SPATEN LATA 473ML - 10
SPATEN LONG NECK 355ML - 10
STELLA ARTOIS LATA 473ML - 11
STELLA ARTOIS LONG 330ML - 12
STELLA ARTOIS PURE GOLD 330ML - 12
STELLA ARTOIS PURE GOLD 473ML - 12
THEREZOPOLIS GOLD LAGER 355ML - 8,5

600ML E LITRO
AMSTEL LAGER 600ML - 12
BRAHMA CHOPP 600ML - 12
AMSTEL LITRAO - 18
CHOPP TUPINIQUIM HELLES 1L - 20
CHOPP TUPINIQUIM IPA 1L - 22
CHOPP TUPINIQUIM PILSEN 1L - 17
CHOPP TUPINIQUIM RED ALE 1L - 20
COLORADO APPIA DESCARTAVEL 600ML - 22
CORONA EXTRA 600ML - 18
ESTRELLA GALICIA 600ML - 18
ORIGINAL 600ML - 15
POLAR 600ML - 12
POLAR LITRAO 1L - 16
SERRAMALTE 600ML - 14
SPATEN 600ML - 15
STELLA ARTOIS ONE WAY 600ML - 18

BEBIDAS EM LATA
SKOL BEATS SENSES 269ML - 13
AMSTEL VIBES LIMAO 269ML - 9
AMSTEL VIBES MORANGO 269ML - 9
MANSAO MAROMBA COMBO JOB / GIN + MELANCIA / TROPICAL DO TIGRINHO / VODKA ENERGETICO / ENERGETICO / MANGA/MARACUJA TIGRINHO / DOUBLE DARKNESS / MACA VERDE - 30
MASCATE MARACUJA 362ML - 18
MASCATE MELANCIA 362ML - 18
SCHWEPPES SPRITZ 250ML - 10
SKOL BEATS GT / RED MIX/ TROPICAL LATA 269ML - 11
SKOL BEATS RED MIX / GREEN MIX / TROPICAL / GT LONG 269ML - 13
SKOL BEATS SENSES LATA 473ML - 15
SMIRNOFF ICE 275ML - 14
XEQUE MATE 355ML - 16

ENERGETICOS
BALY FRUTAS TROPICAIS / MELANCIA / MORANGO E PESSEGO / TRADICIONAL 2L - 20
BALY MACA VERDE / MORANGO E PESSEGO / TRADICIONAL / SEM ACUCAR 473ML - 10
MONSTER ABSOLUT ZERO / DRAGON ICE TEA LIMAO / ENERGY ZERO ACUCAR / KHAOTIC / MANGO LOCO / PACIFIC PUNCH / PEACHY KEEN / PIPELINE PUNCH / RIO PUNCH / THE DOCTOR LT / ULTRA FIESTA MANGO / ULTRA / ULTRA STRAWBERRY DREAM / ULTRA VIOLET 473ML - 16
RED BULL TRADICIONAL / FRUTAS TROPICAIS / MACA SEM ACUCAR / MELANCIA / MELAO MARACUJA / MORANGO E PESSEGO / NECTARINA / SUGAR FREE / SUGAR FREE AMORA / SUGAR FREE POMELO / ZERO 250ML - 15

REFRIGERANTES / SUCOS / CHAS
AGUA COM GAS / SEM GAS 500ML - 5
AGUA DA PEDRA C GAS 2L - 10
AGUA DE COCO KEROCOCO 200 ML - 4,5
AGUA SEM GAS 1.5L - 7,5
COCA COLA TRADICIONAL / SEM ACUCAR 1,5L - 15
COCA COLA TRADICIONAL / SEM ACUCAR / CAFE 220ML - 4
COCA COLA TRADICIONAL / SEM ACUCAR 600ML - 8
COCA COLA KS TRADICIONAL / SEM ACUCAR 250ML - 6,5
COCA COLA LATA 350ML - 6,5
COCA COLA LIGHT 310ML - 6
FANTA LARANJA / MARACUJA / UVA 350ML - 6
FANTA LARANJA 600ML - 7,5
FRUKI GUARANA PET 600ML - 7,5
FYS GUARANA 350ML - 3,49
FYS LIMAO SICILIANO 350ML - 3,49
FYS TONICA LIMAO SICILIANO 350ML - 3,49
GUARANA ANTARCTICA 1,5L - 13
GUARANA ANTARCTICA 600ML - 7
GUARANA ANTARTICA 2L - 16
GUARANA ANTARTICA DIET LATA 350ML - 6
GUARANA ANTARTICA LATA 350ML - 6
GUARANA TUBAINA 355ML - 6,5
H2OH LIMAO 500ML - 8
H2OH LIMONETO 500ML - 8
ICE TEA CHA PESSEGO / ZERO / LIMAO 450ML - 6
KATZE SPEZIALSODA LIM GENG 269ML - 8,9
PEPSI 1,5L - 12
PEPSI 350ML - 6
PEPSI BLACK 350ML - 6
PEPSI TWIST 2L - 14
PEPSI TWIST 350ML - 6
PEPSI TWIST PET 200ML - 3
SCHWEPPES CITRUS 1,5L - 14
SCHWEPPES CITRUS 350ML - 6,5
SCHWEPPES TONICA / ZERO 350ML - 6
SPRITE 220ml - 4
SPRITE 600ml - 7,5
SPRITE REFRIGERANTE 2L - 15
SPRITE REFRIGERANTE LATA 350ML - 6
TONICA ANTARCTICA LATA 350ML - 0
TONICA SCHWEPPES SEM ACUCAR 220ML - 4,5
CHA BAER MATE 350ML - 14
DEL VALLE MANGA / MARACUJA / PESSEGO / UVA 290ML - 6
LEAO CHA VERDE LIMAO 450ML - 6

ISOTONICOS
GATORADE BERRY BLUE / FRUTAS CITRICAS / MORANGO-MARACUJA 500ML - 8,5
I9 POWERADE FRUTAS TROPICAIS / MIX DE FRUTAS / UVA 500ML - 7,5

DESTILADOS
APEROL APERITIVO 750ML - 80
BITTER CAMPARI 998ml - 90
BITTER CYNAR 910ML - 30
CACHACA 51 965ml - 25
CACHACA SAGATIBA CRISTALINA 700ml - 34,9
CACHACA VELHO BARREIRO 910ML - 28
ESPUMANTE SALTON SERIES BRUT 750ML - 37,9
ESPUMANTE SALTON SERIES DEMI SEC 750ML - 37,9
ESPUMANTE SALTON SERIES MOSCATEL 750ML - 37,9
ESPUMANTE SALTON SERIES MOSCATEL ROSE 750ML - 37,9
FERNET BRANCA 1000ML - 170
FERNET BUHERO GARRAFA 700ML - 154,9
GIN BOMBAY SAPPHIRE 750ML - 169,9
GIN GORDONS GARRAFA - 90
GIN ROCKS 995ML - 47,9
GIN TANQUERAY 750ML - 169,9
LICOR 43 GARRAFA - 160
LICOR AMARULA 750ML - 130
LICOR BALLENA CHOCOLATE GARRAFA 750ML - 169,9
LICOR BALLENA COCO GARRAFA 750ML - 169,9
LICOR BALLENA MORANGO GARRAFA 750ML - 169,9
LICOR DON LUIZ DULCE DE LECHE GARRAFA 750ML - 129,9
LICOR FIREBALL 1 LITRO - 189,9
LICOR FIREBALL 750 ML - 160
LICOR JAGERMAISTER 1L - 190
LICOR JAGERMEISTER 700ML - 160
LICOR JAGERMEISTER ORANGE 1L - 259,9
LICOR JAMBU POWER JAM 750ML - 95
RUM BACARDI CARTA BLANCA 980 ML - 64,9
RUM MALIBU 750ML - 99
RUM MONTILLA GARRAFA - 57
TEQUILA JOSE CUERVO 750ML - 194,9
VERMUT CINZANO ROSSO 1L - 57
VODKA ABSOLUT ORIGINAL 1L - 154,9
VODKA KISLLA VIDRO 900ML - 21,9
VODKA NATASHA 900ML - 29,9
VODKA ORLOFF VODKA 1L - 46,99
VODKA SKYY 1L - 42
VODKA SMIRNOFF 1L - 52,9
VODKA WALESA PET 966ML - 18,9
VODKA WALESA VIDRO 950ML - 31,9
WHISKY BUCHANANS DELUXE 12 ANOS 1L - 249,9
WHISKY CHIVAS REGAL 12 YO 1L - 214,9
WHISKY JACK DANIELS 1L - 189,9
WHISKY JACK DANIELS GREEN APPLE 1L - 189,9
WHISKY JACK DANIELS HONEY 1L - 189,9
WHISKY JOHNNIE WALKER BLACK LABEL 1L - 219,9
WHISKY JOHNNIE WALKER RED LABEL 1L - 139,9
WHISKY OLD EIGHT 900ml - 38
WHISKY PASSPORT SELECTION 1L - 79,9
WHISKY WHITE HORSE 1L - 104,99

ESPUMANTES E VINHOS
ESPUMANTE ROSE SAN MARTIN MOSCATEL 660 ML - 20
FRISANTE ALMADEN BRANCO MOSCATEL 750ML - 39,9
FRISANTE ALMADEN ROSE MOSCATEL 750ML - 39,9
VINHO ALMADEN CABERNET SAUVINGNON 750ML - 36,9
VINHO ALMADEN CHARDONNAY 750ML - 44,9
VINHO ALMADEN MERLOT 750ML - 36,9
VINHO ALMADEN SAUVIGNON BLANC 750ML - 44,9
VINHO DEL GRANO TINTO SECO / TINTO SUAVE 1,45L - 27,9
VINHO GARRAFAO TINTO SECO 5L - 65
VINHO GATO NEGRO CABERNET SAUV / CARMENERE / MALBEC / MERLOT 750ML - 44,9
VINHO GATO NEGRO CHARDONNAY 750ML - 49,9
VINHO MARCUS JAMES CHARDONNAY - 29,9
VINHO SANGUE DE BOI TINTO SECO / TINTO SUAVE 750ML - 22
VINHO SANTA HELENA ROSE 750ML - 37
VINHO SUSPEITO BRANCO / ESPUMANTE BRUT / MERLOT ROSE 750ML - 59,9
VINHO SUSPEITO TINTO 750ml - 69,9

BOMBONIERE
HALLS - 4
MENTOS 37,5G - 4
PIRULITO - 0,5
TIC TAC 14,5G - 4
BARRA NUTRATA 40G - 12
RITTER BARRA DE CEREAL 25G - 3,5
CHICLETE MENTOS - 2,99
TRIDENT - 4
ALPINO BARRA 80g - 12
BARRA RECHEADA NEGRESCO NESTLE 90G - 12
BIS 20 UN - 10
BIS XTRA 45G - 7
BOMBOM LACTA OREO - 2,5
BROWNIE - COOKIES - THECOWCOOKIES - 10
CHARGE RECHEADO 90G - 12
CHOCOTRIO 90G - 14
DIAMANTE NEGRO LAKA 80G - 9,99
GAROTO CRUNCH 80G - 10,99
GAROTO NEGRESCO 80G - 10
KIT KAT 41,5G - 6,5
BARRA LACTA - 14
LOLLO CHOCOLATE 28g - 4,5
MM AMENDOIM 40G - 7
NESTLE BATON DUO 16G - 3
NESTLE CHOCOLATE BARRA CRUNCH 80G - 12
PRESTIGIO 33G - 4,5
NESTLE SUFLAIR 80G - 12
ODARA ALFAJOR - 8
OURO BRANCO BOMBOM - 2,5
PACOCA 15G - 1
SNICKERS 45G - 7
STIKADINHO 12,3G - 2,5
TALENTO 85G - 12,5
TRENTO - 5,99
TWIX MINI 15G - 2,5
TWIX ORIGINAL 40G - 7
WAFFER NUTELLA B-READY 22G - 6,5

COMIDAS
PIZZA CONGELADA 300G - 27 (consultar sabores e modo de preparo)
ENROLADAO DE SALSICHA - 10
PAO DE QUEIJO - 6
PAOZOTE DE QUEIJO SALGADO - 8
PAOZOTE DE QUEJO DOCE - 10
PASTEL DE FORNO FRANGO IDEAL - 10
PASTEL FOLHADO CALABRESA IDEAL - 10
PASTEL FOLHADO FRANGO IDEAL - 10
PASTEL FOLHADO SALSICHA IDEAL - 10
PASTEL FRITO DE CARNE - 10
PASTEL FRITO DE QUEIJO - 10
PORCAO DE BATATA FRITA 500G - 22
PORCAO DE PAOZINHO DE ALHO 12un - 24
SANDUBA CLASSICO (TORRADA SIMPLES) - 7
SANDUBA COLONO (COLONIAL SIMPLES) - 9
SANDUBA DA BAITA (COLONIAL COMPLETO) - 19

SALGADINHOS
AMENDOIM JAPONES 145G - 8,49
DORITOS - 6 - 15
FANDANGOS - 2,99 - 8,99
LAYS - 4,99 - 9,99
PINGO DOURO - 5,99
RUFFLES - 4,49 - 9,49
SENSACOES - 5,99
TORCIDA - 3,99
PETTIZ AMENDOIM JAPONES / SAL S PELE 50G - 4,5
POPCORNERS WHITE CHEDDAR 57G - 7,99
SACO DE GELO 3KG - 10

CIGARRO - aqui da pra dizer que o preco e tabelado, e mais pra mostrar as opcoes.
CAMEL BLUE - 8,25
CAMEL DOUBLE MINT & PURPLE - 12,5
CAMEL KRETEK BERRY - 15,25
CAMEL KRETEK MENTHOL - 15,25
CAMEL LEGEND BLUE - 7,75
CAMEL LEGEND YELLOW - 7,75
CAMEL YELLOW - 8,25
CHESTERFIELD BLUE - 9,25
CHESTERFIELD ORIGINAL (VERMELHO) - 9,25
CHESTERFIELD REMIX BEATS - 10
CHESTERFIELD REMIX WILD - 10
CHESTERFIELD TERRAS BRASILEIRAS - 8,75
CIGARRO CAMEL YELLOW TROPICAL - 12,5
CIGARRO ELF 15000 - 160
CIGARRO IGN 1000K - 80
CIGARRO IGN 8000K - 170
CIGARRO VG 1500 - 80
DJARUM BLACK KRETEK - 20,5
DJARUM BLACK MENTHOL - 20,5
DUNHILL AZUL - 12,5
DUNHILL EVOQUE TABACO BLEND - 14
DUNHILL VERMELHO - 12,5
DUNHILL VOYAGE DOUBLE REFRESH - 12,5
DUNHILL VOYAGE MIX REFRESH - 12,5
GUDANG BOX - 60
KENT GREEN MIX BOX - 9,75
KENT PRO BLUE BOX - 7,75
KENT PRO RED BOX - 7,75
KENT PURPLE TWIST BOX - 9,75
L&M BLUE - 11
L&M FIRST CUT BLUE BOX - 7,75
L&M FIRST CUT SILVER BOX - 7,75
L&M FORWARD - 11,25
L&M KRETEK - 12
LUCKY STRIKE BLUE - 7,75
LUCKY STRIKE FRESH DOUBLE ICE X - 11,75
LUCKY STRIKE FRESH ICE - 11
LUCKY STRIKE FRESH WILD - 11,75
LUCKY STRIKE MINT X - 11
MARLBORO FOREST FUSION - 12,5
MARLBORO GOLD - 12,5
MARLBORO GOLD MACO - 10,75
MARLBORO GOLD SELECTION - 7,75
MARLBORO ICE BURST - 12,5
MARLBORO RED - 12,5
MARLBORO RED MACO - 10,75
MARLBORO RED SELECTION - 7,75
MARLBORO TROPICAL FUSION - 12,5
ROTHMANS BLUE - 9
ROTHMANS RED - 9
SAMPOERNA KRETEK - 14,75
SAMPOERNA MENTHOL BOX - 14,75
WINSTON BLUE SELECTED - 7,75

FILTROS E PITEIRAS
FILTRO BEM BOLADO CLASSICO SLIM 6MMX15MM - 12,5
FILTRO BEM BOLADO LONGO 6MMX22MM - 14,5
FILTRO PAPELITO TRADICIONAL 6MM/15MM - 12,5
FILTRO PAPELITO TRADICIONAL LONGO - 14
FILTRO PAPELITO ULTRA LONGO - 16
PITEIRA BEM BOLADO BROWN HIPER LARGE - 8
PITEIRA BEM BOLADO BROWN LARGE - 5
PITEIRA BEM BOLADO BROWN SUPER LARGE - 6,5
PITEIRA LION CIRCUS BROWN REGULAR - 5,5
PITEIRA PAPELITO FUN EXTRA LARGE - 5,5
PITEIRA PAPELITO MEGA LONGA - 8
PITEIRA RAW BLACK - 10,5
PITEIRA RAW CLASSIC TIPS - 7
PITEIRA TATU DO BEM GRANDE - 6

SEDAS
CONE G-ROLLZ STRAWBERRY - 28
HEMP CONE G-ROLLZ MANGO PULP - 29
HEMP CONE LION ROLLING CIRCUS GELATO - 22,9
HEMP WRAP LION ROLLING CIRCUS SABOR SORTIDO - 15
KING BLUNT SABORES - 9,99
SEDA ALEDA CELULOSE 1 1/4 - 5
SEDA ALEDA KS + PITEIRA - 13,5
SEDA ALEDA KS CELULOSE - 6
SEDA AVULSA - 0,25
SEDA BEM BOLADO BROWN 1 1/4 LARGE - 6
SEDA BEM BOLADO BROWN 1 1/4 LARGE 100 FOLHAS - 13
SEDA BEM BOLADO BROWN KS LARGE - 7
SEDA BEM BOLADO BROWN KS SLIM - 7
SEDA BEM BOLADO BROWN LARGE + PITEIRA - 13
SEDA BEM BOLADO BROWN LONG SIZE - 7,5
SEDA BEM BOLADO CONE BROWN C/3 - 11
SEDA BEM BOLADO POP 1 1/4 LARGE - 5,5
SEDA BEM BOLADO POP 1 1/4 SLIM - 5,5
SEDA BEM BOLADO POP KS LARGE - 6
SEDA BEM BOLADO POP KS SLIM - 6
SEDA BEM BOLADO PREMIUM 1 1/4 LARGE - 7
SEDA BEM BOLADO ROLO BROWN 5MTS LARGE - UN - 12
SEDA CELULOSE LION CIRCUS 1 1/4 - 6,5
SEDA ELEMENTS KS BLUE SLIM - 10
SEDA ELEMENTS KS GREEN SLIM - 12
SEDA ELEMENTS KS PINK SLIM - 12
SEDA HONEYPUFF DOLAR - 15
SEDA LION CIRCUS BROWN 1 1/4 - 6,5
SEDA LION CIRCUS BROWN KS - 5
SEDA LION CIRCUS KS + TIPS - 8
SEDA LION CIRCUS SABORIZADA 1 1/4 CHOCOLATE FUNKY - 6
SEDA LION CIRCUS SABORIZADA KS CHOCOLATE FUNKY - 7,5
SEDA LION ROLLING CIRCUS ALFAFA KS - 8
SEDA OCB KS SLIM PREMIUM - 9
SEDA PAPELITO BROWN 1 1/4 LARGE - 5
SEDA PAPELITO BROWN 1 1/4 SLIM - 5
SEDA PAPELITO BROWN KS LARGE - 5,5
SEDA PAPELITO BROWN KS LARGE COM PITEIRA E BANDEJA - 15
SEDA RAW BLACK KING SIZE - 17
SEDA RAW CLASSIC 1 1/4 - 13
SEDA RAW CLASSIC BROWN KS - 14
SEDA RAW CLASSIC SINGLE WIDE - 10
SEDA RAW COM PITEIRA - 25
SEDA RAW ORGANIC HEMP KING SIZE - 13
SEDA SMOKING KINGSIZE BROWN - 9
SEDA TATU DO BEM 1 1/4 LARGE (VERDE) - 4,5
SEDA TATU DO BEM 1 1/4 SLIM (LARANJA) - 4,5
SEDA TATU DO BEM BROWN 1 1/4 - 5
SEDA TATU DO BEM BROWN KS SLIM - 5
SEDA TATU DO BEM KS SLIM (LARANJA) - 5

TABACO
PALHEIRO TRADICIONAL ORIGINAL C/10 - 11,5
TABACO ACREMA 20G - 22
TABACO AMSTERDAM 25G - 22
TABACO ARTESANAL BEM BOLADO 25G - 24
TABACO BE HAPPY 30G - 22
TABACO BOLADO LA REVOLUCION C/10 - 13,9
TABACO D PATRAO 35G - 8
TABACO D PRIMEIRA 35G - 17
TABACO GOLDEN VIRGINIA TABAQUIN C/5 - 16
TABACO HI LATA 80G - 80
TABACO HI POCKET 12G - 17,5
TABACO RAINBOW 25G - 27
TABACO SASSO TAB GOLDEN VIRG 25G - 25
TABACO SASSO VIRG BLEND 25G - 22
TABACO VB VIRGINIA 25G - 18
TABACO VEIO PIMENTA GRANDE 50G - 42
TABACO VEIO PIMENTA ROSIN 25G - 25
"""


def parse_price(raw: str) -> tuple[int, str]:
    numbers = re.findall(r"\d+(?:,\d+)?", raw)
    if not numbers:
        return 0, raw.strip()
    value = float(numbers[0].replace(",", "."))
    cents = int(round(value * 100))
    display = "R$ " + raw.strip()
    return cents, display


def parse_menu_items() -> list[dict]:
    current_slug: Optional[str] = None
    positions: dict[str, int] = {}
    items: list[dict] = []
    for raw_line in MENU_TEXT.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized_header = line.upper()
        if normalized_header.startswith("CIGARRO - "):
            current_slug = "cigarro"
            positions.setdefault(current_slug, 0)
            continue
        if normalized_header in HEADER_TO_SLUG:
            current_slug = HEADER_TO_SLUG[normalized_header]
            positions.setdefault(current_slug, 0)
            continue
        if not current_slug:
            continue
        parts = re.split(r"\s+-\s+", line)
        if len(parts) < 2 or not re.match(r"^\d", parts[1].strip()):
            continue
        name = parts[0].strip()
        price_raw = " - ".join(parts[1:]).strip()
        price_cents, price_display = parse_price(price_raw)
        slug = SPECIAL_SLUGS.get(name.upper()) or f"{current_slug}-{supabase_client._slugify(name)}"
        position = positions[current_slug]
        positions[current_slug] += 1
        items.append({
            "category_slug": current_slug,
            "slug": slug,
            "title": name,
            "price_cents": price_cents,
            "price_display": price_display,
            "position": position,
        })
    return items


def _ensure_collection(persona_id: str, persona_slug: str) -> dict:
    persona_node = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "persona",
        "slug": persona_slug,
        "title": "Baita Conveniencia",
        "summary": "Persona raiz da Baita Conveniencia.",
        "tags": ["baita", "persona"],
        "metadata": {"persona_slug": persona_slug, "protected": True, "created_from": FULL_MENU_SOURCE},
        "status": "validated",
    })
    brand = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "brand",
        "slug": "baita",
        "title": "Baita",
        "summary": "Brand Baita conectada ao cardapio vivo.",
        "tags": ["baita", "brand"],
        "metadata": {"persona_slug": persona_slug, "created_from": FULL_MENU_SOURCE},
        "status": "validated",
    })
    collection = supabase_client.upsert_knowledge_node({
        "persona_id": persona_id,
        "node_type": "product_collection",
        "slug": CARDAPIO_CAMPAIGN_SLUG,
        "title": "Cardapio Baita v14",
        "summary": "Cardapio completo da Baita Conveniencia.",
        "tags": ["product_collection", "cardapio", "baita", "v14"],
        "metadata": {
            "collection_type": "menu",
            "display_name": "Cardapio Baita v14",
            "version": "v14",
            "source_file": "user_catalog_full_menu",
            "created_from": FULL_MENU_SOURCE,
        },
        "status": "validated",
    })
    if persona_node and brand:
        _edge(persona_node, brand, "contains", persona_id, weight=1.0, primary=True)
    if brand and collection:
        _edge(brand, collection, "brand_has_collection", persona_id, weight=0.9, primary=True)
    return collection


def _ensure_category_asset(persona_id: str, persona_slug: str, image_dir: Path, category: dict, spec: dict, gallery: dict) -> dict:
    image_path = _find_image(image_dir, spec["cover_aliases"][0], {}, spec["cover_aliases"])
    asset = _create_asset_row(
        persona_id=persona_id,
        persona_slug=persona_slug,
        image_path=image_path,
        campaign_slug=CARDAPIO_CAMPAIGN_SLUG,
        asset_function="category_cover",
        usage=f"Capa aprovada da categoria {spec['title']} no cardapio Baita.",
    )
    asset_meta = dict(asset.get("metadata") or {})
    asset_meta.update({
        "validation_status": "approved",
        "approved": True,
        "category_slug": spec["slug"],
        "asset_function": "category_cover",
        "created_from": FULL_MENU_SOURCE,
    })
    supabase_client.update_asset(asset["id"], {"metadata": asset_meta, "status": "ready"})
    asset["metadata"] = asset_meta
    asset_node = _ensure_asset_node(
        asset,
        persona_id,
        persona_slug,
        title=f"Capa {spec['title']}",
        summary=f"Asset aprovado para capa da categoria {spec['title']}.",
        parent=category,
    )
    asset_node = supabase_client.update_knowledge_node(asset_node["id"], {"status": "validated"}) or asset_node
    gallery_edge = supabase_client.upsert_knowledge_edge(
        asset_node["id"],
        gallery["id"],
        "gallery_asset",
        persona_id=persona_id,
        weight=0.95,
        metadata={"created_from": FULL_MENU_SOURCE, "status": "approved", "primary_tree": False, "active": True},
    )
    for source in [category]:
        supabase_client.upsert_knowledge_edge(
            source["id"],
            asset_node["id"],
            "uses_asset",
            persona_id=persona_id,
            weight=0.9,
            metadata={"created_from": FULL_MENU_SOURCE, "role": "category_cover", "status": "approved", "sort_order": 0, "primary_tree": False, "active": True},
        )
    supabase_client.update_asset_graph_refs(
        asset["id"],
        knowledge_node_id=asset_node["id"],
        gallery_edge_id=(gallery_edge or {}).get("id"),
        parent_node_id=category["id"],
        parent_edge_id=(gallery_edge or {}).get("id"),
    )
    return {"asset": asset, "asset_node": asset_node, "gallery_edge": gallery_edge}


def seed_full_menu(image_dir: Path, persona_slug: str = "baita-conveniencia") -> dict:
    persona = supabase_client.get_persona(persona_slug)
    if not persona:
        raise RuntimeError(f"Persona not found: {persona_slug}")
    persona_id = persona["id"]
    gallery = supabase_client.ensure_gallery_node(persona_id)
    if not gallery:
        raise RuntimeError("Could not ensure Gallery node")
    collection = _ensure_collection(persona_id, persona_slug)

    category_nodes: dict[str, dict] = {}
    entity_nodes: dict[str, dict] = {}
    cover_results = []
    for spec in CATEGORY_SPECS:
        category = supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            # The public menu contract reads canonical product_group nodes.
            # Keep the human-facing category vocabulary in the metadata/title,
            # but materialize the graph with the canonical taxonomy.
            "node_type": "product_group",
            "slug": spec["slug"],
            "title": spec["title"],
            "summary": f"Categoria do cardapio Baita: {spec['title']}.",
            "tags": ["baita", "category", spec["slug"]],
            "metadata": {
                "persona_slug": persona_slug,
                "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
                "position": spec["position"],
                "sort_order": spec["position"],
                "eyebrow": spec["eyebrow"],
                "created_from": FULL_MENU_SOURCE,
            },
            "status": "validated",
        })
        entity = supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "node_type": "entity",
            "slug": f"categoria-{spec['slug']}",
            "title": spec["title"],
            "summary": f"Entidade de agrupamento da categoria {spec['title']} no cardapio.",
            "tags": ["baita", "entity", "category_entity", spec["slug"]],
            "metadata": {
                "persona_slug": persona_slug,
                "entity_role": "category_group",
                "category_slug": spec["slug"],
                "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
                "created_from": FULL_MENU_SOURCE,
            },
            "status": "validated",
        })
        category_nodes[spec["slug"]] = category
        entity_nodes[spec["slug"]] = entity
        _edge(collection, category, "collection_has_category", persona_id, weight=0.88, primary=True)
        _edge(category, entity, "same_topic_as", persona_id, weight=0.75)
        cover = _ensure_category_asset(persona_id, persona_slug, image_dir, category, spec, gallery)
        _edge(entity, cover["asset_node"], "uses_asset", persona_id, weight=0.9)
        asset_url = (cover["asset"] or {}).get("url")
        category_meta = dict(category.get("metadata") or {})
        category_meta.update({
            "cover_asset_id": (cover["asset"] or {}).get("id"),
            "cover_asset_node_id": (cover["asset_node"] or {}).get("id"),
            "cover_url": asset_url,
            "cover_alt": f"Capa {spec['title']}",
        })
        supabase_client.update_knowledge_node(category["id"], {"metadata": category_meta, "status": "validated"})
        cover_results.append({"category_slug": spec["slug"], "asset_id": (cover["asset"] or {}).get("id"), "asset_node_id": (cover["asset_node"] or {}).get("id")})

    product_count = 0
    for item in parse_menu_items():
        category = category_nodes[item["category_slug"]]
        product = supabase_client.upsert_knowledge_node({
            "persona_id": persona_id,
            "node_type": "product",
            "slug": item["slug"],
            "title": item["title"],
            "summary": f"{item['title']} - {item['price_display']}.",
            "tags": ["baita", "product", item["category_slug"]],
            "metadata": {
                "persona_slug": persona_slug,
                "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
                "category_slug": item["category_slug"],
                "price_cents": item["price_cents"],
                "price_display": item["price_display"],
                "position": item["position"],
                "visible": True,
                "source": FULL_MENU_SOURCE,
                "created_from": FULL_MENU_SOURCE,
            },
            "status": "validated",
        })
        if product:
            _edge(category, product, "category_has_product", persona_id, weight=0.86, primary=True)
            _edge(product, collection, "part_of_collection", persona_id, weight=0.7)
            product_count += 1

    return {
        "ok": True,
        "persona_slug": persona_slug,
        "collection_slug": CARDAPIO_CAMPAIGN_SLUG,
        "categories": len(CATEGORY_SPECS),
        "entities": len(entity_nodes),
        "products": product_count,
        "category_covers": cover_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-dir", required=True)
    parser.add_argument("--persona-slug", default="baita-conveniencia")
    args = parser.parse_args()
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(API_DIR / ".env", override=False)
    result = seed_full_menu(Path(args.image_dir).resolve(), args.persona_slug)
    import json

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
