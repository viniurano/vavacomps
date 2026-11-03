# Configurar a atualização manual no Netlify

O site continua estático. A função do Netlify apenas dispara uma execução do GitHub Actions; o Python roda no runner do GitHub, grava os JSONs na branch de teste e o Netlify publica a atualização automaticamente.

## 1. Conferir a publicação

- Repositório: `viniurano/vavacomps`
- Branch de deploy: `feature/backend-dinamico-v3`
- O arquivo `netlify.toml` configura a publicação da raiz e a pasta `netlify/functions`.

Não altere o repositório de produção.

## 2. Criar um token restrito no GitHub

Crie um *fine-grained personal access token* limitado somente ao repositório `viniurano/vavacomps`, com a permissão de repositório **Actions: Read and write**. O token é usado exclusivamente para solicitar o workflow `v4-auto-sync.yml`.

Não coloque esse token no HTML, no JavaScript do navegador ou em arquivos do repositório.

## 3. Cadastrar a variável no Netlify

No painel do site Netlify:

1. Abra **Site configuration → Environment variables**.
2. Adicione a variável `GITHUB_TOKEN`.
3. Cole o token como valor e aplique ao contexto de produção.
4. Salve e faça um novo deploy para a Function receber a variável.

## 4. Testar

1. Abra a VCT Comps no endereço do site.
2. Selecione uma equipe e um campeonato.
3. Clique em **Atualizar dados do time**.
4. O botão deve informar que a solicitação foi enviada ao GitHub Actions.
5. Em **GitHub → Actions**, acompanhe o workflow **Vava v4 - sincronizacao automatica (branch de testes)**.
6. Quando terminar, confira o commit em `feature/backend-dinamico-v3` dentro de `dados/v4/eventos/`. O Netlify fará um novo deploy após o commit.

A solicitação é assíncrona: o botão confirma que o GitHub aceitou o disparo, não que a coleta já terminou. Aguarde o workflow e o deploy antes de recarregar a página.

## Observações

- O token fica somente nas variáveis de ambiente do Netlify; não é enviado ao navegador.
- A Function aceita chamadas originadas do domínio de teste atual. Se o domínio do site mudar, atualize a lista `ALLOWED_ORIGINS` em `netlify/functions/refresh-data.mjs`.
- A atualização manual é por equipe e campeonato. A rotina diária de descoberta de eventos e a coleta agendada continuam independentes.
