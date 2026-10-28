# dra-livia

Ferramentas do escritório.

## Skill do Claude: `responder-email`

Redige respostas de e-mail no Gmail **com a voz e a formatação de quem está usando**. Serve qualquer pessoa do escritório: cada pessoa conecta a própria conta Gmail, e o estilo vem dos e-mails que ela mesma enviou. Resume a conversa, confere a resposta com o histórico, salva o rascunho na mesma conversa e mostra no chat. **Nunca envia.**

A skill fica neste repositório, em [`responder-email/`](responder-email): `SKILL.md` (instruções) e `scripts/` (acesso ao Gmail). É uma skill avulsa, não um plugin. O Claude só encontra skills em `~/.claude/skills/`, então lá fica um link para esta pasta.

### Instalação (cada pessoa, uma vez)

1. Clonar este repositório e criar o link para a skill (rodar dentro da pasta do repositório):
   ```bash
   ln -s "$PWD/responder-email" ~/.claude/skills/responder-email
   ```
   Assim, um `git pull` já atualiza a skill.
2. `pip install -r ~/.claude/skills/responder-email/requirements.txt`
3. Credenciais do Google em variáveis de ambiente: ver a seção "Configuração do Google" no `SKILL.md`. O `GOOGLE_CLIENT_ID` e o `GOOGLE_CLIENT_SECRET` podem ser os do escritório; o `GOOGLE_REFRESH_TOKEN` é sempre o da própria pessoa. Não é preciso obtê-lo à mão: quando ele falta ou expira, o Claude abre o login do Google e grava o token novo no `~/.zshrc` sozinho.
4. No Gmail, criar um marcador (o escritório pode combinar um nome único, ex.: `email-style`) e aplicá-lo a 8 a 20 e-mails que a pessoa enviou; definir `EMAIL_STYLE_LABEL`. Sem isso, a skill usa os últimos 10 e-mails enviados.
5. Verificar: `python ~/.claude/skills/responder-email/scripts/google_client.py --check`

### Regras do escritório

A seção "Regras do escritório" do `SKILL.md` guarda as regras comuns a toda a equipe (fontes do caso, Cc obrigatório, alertas, regras da casa, frases proibidas, glossário, tipos de e-mail). Cada subseção começa como `_Não configurado._` e, enquanto estiver assim, a skill a ignora. Nada que seja de uma só pessoa (nome, assinatura, OAB, tom) entra lá.

## Extensões do Chrome

- [tradutor_aulas](tradutor_aulas): legendas ES → PT-BR para o Google Meet e para vídeos do Google Drive.
