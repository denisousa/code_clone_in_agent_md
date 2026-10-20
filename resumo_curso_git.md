# Resumo — Curso de Git

## Dia 1

### 1. Introdução ao Git
- Controle de versão, o que é Git, repositório local e remoto
- Working directory → Staging area → Repository
- Fluxo básico de trabalho

### 2. Comandos base
| Comando | Função |
|---|---|
| `git init` / `git clone` | Criar ou copiar repositório |
| `git status` / `git log` / `git diff` | Inspecionar estado e histórico |
| `git add` / `git commit` | Registrar alterações |
| `git push` / `git pull` / `git fetch` | Sincronizar com remoto |

> `git pull` = fetch + merge automático; `git fetch` só baixa sem integrar.

### 3. .gitignore
- Evitar versionar `node_modules/`, `.env`, arquivos de build/temporários
- Se um arquivo sensível foi commitado: remover do histórico com cuidado

### 4. Autenticação com token (PAT)
- Senha não é mais aceita; usar Personal Access Token
- Credential Manager para armazenar credenciais com segurança

### 5. VSCode com Git
- Aba **Source Control**: stage, commit, push/pull e diff direto na IDE
- Resolução simples de conflitos pela interface

### 6. Commit Patterns — Conventional Commits
```
<tipo>: <descrição curta>

feat | fix | docs | style | refactor | test | chore
```
Exemplos: `feat: adiciona tela de login` / `fix: corrige validação do formulário`

---

## Dia 2

### 7. Branches e Feature Branch
- Nunca trabalhar direto na `main`
- Comandos: `git branch`, `git checkout`/`git switch`, `git merge`, `git branch -d`
- Nomenclatura: `feature/login`, `fix/form-validation`, `hotfix/payment-error`

### 8. Git Flow
| Branch | Papel |
|---|---|
| `main` | Código em produção |
| `develop` | Integração contínua |
| `feature/*` | Novas funcionalidades |
| `release/*` | Preparação de versão |
| `hotfix/*` | Correções urgentes em produção |

> Indicado para times maiores ou projetos com ciclos de release definidos.

### 9. Pull Request / Merge Request
- Abrir PR após branch atualizada, commits organizados, sem arquivos sensíveis
- Fluxo: abrir → revisar → comentar/sugerir → aprovar → merge

### 10. Template de Pull Request
- Arquivo em `.github/pull_request_template.md`
- Seções típicas: Descrição, Tipo de alteração, Como testar, Checklist

### 11. Conflitos de merge
- Ocorrem quando dois branches alteram as mesmas linhas
- Resolver no VSCode: escolher versão, salvar, `git add`, `git commit`
- Prevenção: branches pequenas e de vida curta, branches sempre atualizadas

### 12. Desfazer alterações com segurança
| Situação | Comando |
|---|---|
| Arquivo não commitado | `git restore arquivo.txt` |
| Arquivo no stage | `git restore --staged arquivo.txt` |
| Corrigir último commit | `git commit --amend` |
| Reverter commit (seguro) | `git revert <hash>` |
| Mover HEAD (cuidado) | `git reset` |

> Preferir `revert` a `reset` em branches compartilhadas — não reescreve histórico público.
