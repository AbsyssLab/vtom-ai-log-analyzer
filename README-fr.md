# Analyseur de Logs VTOM avec AI
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE.md)&nbsp;
[![fr](https://img.shields.io/badge/lang-en-red.svg)](README.md)  

Ce script permet d'analyser automatiquement les logs d'erreur VTOM (Visual TOM) en utilisant des modèles de langage (LLM) pour identifier les problèmes et proposer des solutions.

## Fonctionnalités

- **Analyse automatique** des fichiers de logs de VTOM
- **Support multi-fournisseurs LLM** : Groq, OpenAI, Anthropic Claude, Google Gemini, Mistral AI, Together AI, Cohere
- **Analyse structurée** avec identification des erreurs, causes et solutions
- **Résumé en français ou anglais** pour une compréhension rapide
- **Gestion des erreurs** robuste avec fallback
- **Envoi de mails** avec Azure AD ou SMTP

# Disclaimer
Aucun support ni garanties ne seront fournis par Absyss SAS pour ce projet et fichiers associés. L'utilisation est à vos propres risques.

Absyss SAS ne peut être tenu responsable des dommages causés par l'utilisation d'un des fichiers mis à disposition dans ce dépôt Github.

Il est possible de faire appel à des jours de consulting pour l'implémentation.

# Prérequis

  * Visual TOM 7.1.2 or supérieur
  * Une clé API pour un fournisseur LLM
  * Python 3.10 ou supérieur sur le serveur Visual TOM

# Consignes
## Configuration des fournisseurs LLM

Le projet supporte maintenant 7 fournisseurs LLM différents.
  * Installer la bibliothèque liée au fournisseur que vous voulez utiliser (voir requirements.txt)
  * Configurer la clé API dans le fichier .env

Les paramètres suivants sont optionnels et peuvent être configurés dans le fichier .env:
  * Model
  * Temperature
  * Nombre maximum de tokens

## Configuration de l'envoi de mails

Le script supporte deux méthodes d'envoi de mails:
  * Azure AD + Microsoft Graph
  * SMTP classique

Vous pouvez configurer la méthode à utiliser dans le fichier .env.

## Configuration du serveur VTOM

Vous pouvez configurer le serveur VTOM dans le fichier .env.
  * Serveur VTOM
  * Port VTOM
  * Clé API VTOM
  * Version API Domain VTOM
  * Version API Monitoring VTOM

## Usage

Créer une alarme dans VTOM pour déclencher le script en cas d'erreur.
```bash
python vtom_api_analyzer.py -f {VT_JOB_LOG_OUT_NAME} -e {VT_ENVIRONMENT_NAME} -a {VT_APPLICATION_NAME} -j {VT_JOB_NAME} --to {VT_EMAIL_RECIPIENTS} --agent {VT_JOB_HOSTS_ERROR}
```
Il est possible de configurer le langage de l'analyse et de l'email dans le fichier .env (optionnel).

Le mail envoyé contient l'analyse de l'erreur, l'instruction du traitement ou un lien s'il s'agit d'une consigne externe, le contexte du traitement (variables, etc.) et les logs du Traitement en pièce jointes.

### Limitations
Les Traitements Multi-agents ne sont pas supportés.  
Si l'instruction est externe, le LLM ne pourra pas l'analyser.

# Licence
Ce projet est sous licence Apache 2.0. Voir le fichier [LICENCE](license) pour plus de détails.


# Code de conduite
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-v2.1%20adopted-ff69b4.svg)](code-of-conduct.md)  
Absyss SAS a adopté le [Contributor Covenant](CODE_OF_CONDUCT.md) en tant que Code de Conduite et s'attend à ce que les participants au projet y adhère également. Merci de lire [document complet](CODE_OF_CONDUCT.md) pour comprendre les actions qui seront ou ne seront pas tolérées.
