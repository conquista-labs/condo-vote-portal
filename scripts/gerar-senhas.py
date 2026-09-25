#!/usr/bin/env python3
"""
Gera a planilha de senhas de votação a partir da planilha bruta de apartamentos.

Uso:
  python3 scripts/gerar-senhas.py ~/Downloads/Vista_Linda_Apartamentos_25_09_2026.xlsx
  python3 scripts/gerar-senhas.py BRUTA.xlsx --manter publicada
  python3 scripts/gerar-senhas.py BRUTA.xlsx --manter senhas_anteriores.csv

O que faz:
  - junta as unidades de um mesmo CPF/CNPJ em uma linha só;
  - Número de votos = quantidade de unidades (ex.: "02-05/13" conta 2);
  - Tipo da Pessoa = Física (CPF) ou Jurídica (CNPJ);
  - gera senhas fixas no formato A123B45 (sem RANDBETWEEN, não mudam sozinhas);
  - com --manter, reaproveita a senha de quem já estava na lista anterior.

Saída: um CSV ao lado da planilha bruta (fora do repositório), no mesmo layout
da aba publicada que a função netlify/functions/buscar-senha.js lê.
Só usa a biblioteca padrão do Python.
"""

import argparse
import csv
import io
import re
import secrets
import string
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

PLANILHA_PUBLICADA = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vQDGBReG32dsUTOkPVkeXKaAJR4idiXIocV-I7RZAML5C1rQdkW5ia8ORX642iKbA"
    "/pub?output=csv"
)

# Mesmo cabeçalho da aba publicada. A função lê Documento (col. 3), Nome (col. 4)
# e Senha de Votação (col. 6), então a ordem das colunas não pode mudar.
CABECALHO = [
    "Unidade",
    "Tamanho",
    "Tipo da Pessoa",
    "Documento",
    "Nome",
    "Senha de Gerada",
    "Senha de Votação",
    "Número de votos",
]

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


# ── Leitura de .xlsx sem dependências ─────────────────────────────────────


def _indice_coluna(ref):
    letras = re.match(r"[A-Z]+", ref).group()
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n - 1


def ler_xlsx(caminho):
    """Retorna as linhas da primeira aba como listas de strings."""
    with zipfile.ZipFile(caminho) as z:
        compartilhadas = []
        if "xl/sharedStrings.xml" in z.namelist():
            raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in raiz.findall("m:si", NS):
                compartilhadas.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        primeira = wb.find("m:sheets/m:sheet", NS)
        rel_id = primeira.get(f"{{{NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        alvo = next(r.get("Target") for r in rels.findall("rel:Relationship", NS) if r.get("Id") == rel_id)
        alvo = alvo.lstrip("/")
        caminho_aba = alvo if alvo.startswith("xl/") else f"xl/{alvo}"

        linhas = []
        for row in ET.fromstring(z.read(caminho_aba)).iter(f"{{{NS['m']}}}row"):
            valores = {}
            for c in row.findall("m:c", NS):
                tipo = c.get("t")
                if tipo == "inlineStr":
                    valor = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                else:
                    v = c.find("m:v", NS)
                    valor = v.text if v is not None else ""
                    if tipo == "s":
                        valor = compartilhadas[int(valor)]
                valores[_indice_coluna(c.get("r"))] = valor or ""
            if valores:
                linhas.append([valores.get(i, "") for i in range(max(valores) + 1)])
        return linhas


# ── Regras ────────────────────────────────────────────────────────────────


def contar_unidades(unidade):
    """'02-05' → 1, '02-05/13' → 2, '03/03/06-13/14/07' → 3."""
    if "-" not in unidade:
        return 1
    return len([p for p in unidade.split("-", 1)[1].split("/") if p.strip()])


def tipo_pessoa(documento):
    digitos = re.sub(r"\D", "", documento)
    return "Jurídica" if len(digitos) == 14 else "Física"


def nova_senha(usadas):
    while True:
        s = (
            secrets.choice(string.ascii_uppercase)
            + str(secrets.randbelow(900) + 100)
            + secrets.choice(string.ascii_uppercase)
            + str(secrets.randbelow(90) + 10)
        )
        if s not in usadas:
            usadas.add(s)
            return s


def somar_tamanhos(tamanhos):
    try:
        total = sum(float(t.strip()) for t in tamanhos)
    except ValueError:
        return " / ".join(t.strip() for t in tamanhos)
    return f"{total:.2f}".rstrip("0").rstrip(".")


def carregar_senhas_anteriores(origem):
    """Lê um CSV no layout da aba publicada e devolve {documento: senha}."""
    if origem == "publicada":
        origem = PLANILHA_PUBLICADA
    if origem.startswith("http"):
        with urllib.request.urlopen(origem) as resp:
            texto = resp.read().decode("utf-8")
    else:
        texto = Path(origem).read_text(encoding="utf-8-sig")

    leitor = csv.DictReader(io.StringIO(texto))
    senhas = {}
    for linha in leitor:
        doc = (linha.get("Documento") or "").strip()
        senha = (linha.get("Senha de Votação") or "").strip()
        if doc and senha:
            senhas[doc] = senha
    return senhas


# ── Principal ─────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Gera a planilha de senhas de votação.")
    ap.add_argument("bruta", help="planilha .xlsx exportada do sistema do condomínio")
    ap.add_argument(
        "--manter",
        metavar="ORIGEM",
        help="reaproveita senhas já distribuídas: 'publicada' (planilha do site) ou um .csv",
    )
    ap.add_argument("-o", "--saida", help="caminho do CSV gerado (padrão: ao lado da bruta)")
    args = ap.parse_args()

    bruta = Path(args.bruta).expanduser()
    linhas = ler_xlsx(bruta)
    cabecalho = [c.strip() for c in linhas[0]]
    faltando = [c for c in ("Unidade", "Tamanho", "Documento", "Nome") if c not in cabecalho]
    if faltando:
        sys.exit(f"Colunas não encontradas na planilha bruta: {', '.join(faltando)}")
    col = {nome: cabecalho.index(nome) for nome in cabecalho}

    def campo(linha, nome):
        i = col[nome]
        return linha[i].strip() if i < len(linha) else ""

    # Agrupa por documento, preservando a ordem da planilha
    grupos = {}
    avisos = []
    for n, linha in enumerate(linhas[1:], start=2):
        if not any(v.strip() for v in linha):
            continue
        unidade, doc, nome = campo(linha, "Unidade"), campo(linha, "Documento"), campo(linha, "Nome")
        if not doc or not nome:
            avisos.append(f"linha {n} ({unidade or 'sem unidade'}): sem documento ou nome, ignorada")
            continue
        g = grupos.setdefault(doc, {"nome": nome, "unidades": [], "tamanhos": []})
        g["unidades"].append(unidade)
        g["tamanhos"].append(campo(linha, "Tamanho"))

    anteriores = carregar_senhas_anteriores(args.manter) if args.manter else {}
    usadas = set(anteriores.values())
    mantidas = 0

    saida_linhas = []
    for doc, g in grupos.items():
        if doc in anteriores:
            senha = anteriores[doc]
            mantidas += 1
        else:
            senha = nova_senha(usadas)
        saida_linhas.append(
            [
                ", ".join(g["unidades"]),
                somar_tamanhos(g["tamanhos"]),
                tipo_pessoa(doc),
                doc,
                g["nome"],
                senha,
                senha,
                sum(contar_unidades(u) for u in g["unidades"]),
            ]
        )

    saida = Path(args.saida).expanduser() if args.saida else bruta.with_name(f"Senhas_votacao_{bruta.stem}.csv")
    with open(saida, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CABECALHO)
        w.writerows(saida_linhas)

    agrupados = [(d, g["unidades"]) for d, g in grupos.items() if len(g["unidades"]) > 1]
    print(f"✓ {len(saida_linhas)} proprietários, {sum(l[-1] for l in saida_linhas)} votos no total")
    if args.manter:
        print(f"  {mantidas} senhas mantidas da lista anterior, {len(saida_linhas) - mantidas} novas")
    for doc, unidades in agrupados:
        print(f"  agrupado: {grupos[doc]['nome']} → {', '.join(unidades)}")
    for a in avisos:
        print(f"  ⚠ {a}")
    print(f"\nArquivo gerado: {saida}")


if __name__ == "__main__":
    main()
