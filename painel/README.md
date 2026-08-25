# Painel de Rega (Streamlit)

Painel web para ver o status das plantas e registrar rega com um clique.

## Rodar localmente

1. Na raiz do repositório, copie `.streamlit/secrets.toml.example` para
   `.streamlit/secrets.toml` e preencha com as credenciais reais do Turso e
   a senha que você quer usar no painel.
2. Na raiz do repositório, instale as dependências (o core do projeto mais
   as do painel): `pip install -r requirements.txt -r painel/requirements.txt`
   (use `--break-system-packages` se necessário, ou um virtualenv).
3. Rode: `streamlit run painel/app.py`
4. Abra o link que aparecer no terminal (geralmente http://localhost:8501).

## Publicar no Streamlit Community Cloud

1. Suba este repositório pro GitHub, branch `main`.
2. Em https://share.streamlit.io, clique em "New app", escolha o
   repositório e o arquivo `painel/app.py` como ponto de entrada.
3. Em "Advanced settings" → "Secrets", cole o conteúdo do seu
   `.streamlit/secrets.toml` (as mesmas 3 chaves: `TURSO_DATABASE_URL`,
   `TURSO_AUTH_TOKEN`, `PAINEL_SENHA`).
4. Publique. Todo `git push` na `main` que mexer em `painel/` atualiza o
   app publicado automaticamente.
