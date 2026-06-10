const SHEET_CSV_URL =
  "https://docs.google.com/spreadsheets/d/e/2PACX-1vQDGBReG32dsUTOkPVkeXKaAJR4idiXIocV-I7RZAML5C1rQdkW5ia8ORX642iKbA/pub?gid=827876935&single=true&output=csv";

export default async (req) => {
  // Só aceita POST
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ erro: "Método não permitido" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  let cpfBuscado;
  try {
    const body = await req.json();
    cpfBuscado = (body.cpf || "").trim();
  } catch {
    return new Response(JSON.stringify({ erro: "Requisição inválida" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!cpfBuscado) {
    return new Response(JSON.stringify({ erro: "CPF não informado" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Busca o CSV no servidor (nunca exposto ao browser)
  let csvText;
  try {
    const resp = await fetch(SHEET_CSV_URL);
    if (!resp.ok) throw new Error("Falha ao acessar planilha");
    csvText = await resp.text();
  } catch {
    return new Response(
      JSON.stringify({ erro: "Erro ao consultar planilha" }),
      {
        status: 502,
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  // Procura só o CPF solicitado — sem retornar os outros
  const linhas = csvText.trim().split("\n").slice(1);
  for (const linha of linhas) {
    const cols = linha.match(/(".*?"|[^,]+)/g) || [];
    const cpf = (cols[3] || "").replace(/"/g, "").trim();
    const nome = (cols[4] || "").replace(/"/g, "").trim();
    const senha = (cols[5] || "").replace(/"/g, "").trim();

    if (cpf === cpfBuscado) {
      return new Response(JSON.stringify({ nome, senha }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  // CPF não encontrado — não revela se existe ou não na lista
  return new Response(JSON.stringify({ erro: "CPF não encontrado" }), {
    status: 404,
    headers: { "Content-Type": "application/json" },
  });
};

export const config = { path: "/api/buscar-senha" };
