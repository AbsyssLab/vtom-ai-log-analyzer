# VTOM AI Log Analyzer
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE.md)&nbsp;
[![fr](https://img.shields.io/badge/lang-fr-yellow.svg)](README-fr.md)  

This project allows to analyze VTOM logs with AI. Several LLM providers are supported.
The script retrieves logs via API, extracts job instructions and context, then uses an LLM to analyze errors and propose solutions.
The results are sent by email to the specified recipients. Azure AD and SMTP are supported.

## Features

- Automatic analysis of VTOM logs
- Support for multiple LLM providers: Groq, OpenAI, Anthropic Claude, Google Gemini, Mistral AI, Together AI, Cohere
- Structured analysis with identification of errors, causes and solutions
- French or English summary for quick understanding
- Robust error handling with fallback

# Disclaimer
No Support and No Warranty are provided by Absyss SAS for this project and related material. The use of this project's files is at your own risk.

Absyss SAS assumes no liability for damage caused by the usage of any of the files offered here via this Github repository.

Consultings days can be requested to help for the implementation.

# Prerequisites

  * Visual TOM 7.1.2 or greater
  * API Token for an LLM provider
  * Python 3.10 or greater on Visual TOM server

# Instructions

## Configuration of LLM providers

The project now supports 7 different LLM providers.
  * Install the library related to the provider you want to use (see requirements.txt)
  * Configure the API key in the .env file

The following parameters are optional and can be configured in the .env file:
  * Model
  * Temperature
  * Maximum number of tokens

## Configuration of the email sending

The script supports two different methods of sending emails:
  * Azure AD + Microsoft Graph
  * SMTP classic

You can configure the method to use in the .env file.

## Configuration of the VTOM server

You can configure the VTOM server in the .env file.
  * VTOM server
  * VTOM port
  * VTOM API key
  * VTOM Domain API version
  * VTOM Monitoring API version

## Usage

Create an alarm in VTOM to trigger the script in case of error.
```bash
python vtom_api_analyzer.py -f {VT_JOB_LOG_OUT_NAME} -e {VT_ENVIRONMENT_NAME} -a {VT_APPLICATION_NAME} -j {VT_JOB_NAME} --to {VT_EMAIL_RECIPIENTS} --agent {VT_JOB_HOSTS_ERROR}
```
It is possible to configure the language of the analysis and the email in the .env file (optional).  
The email sent contains the analysis of the error, the instruction of the job or an external link if it is an external instruction, the context of the job (variables, etc.) and the logs of the job as attachments. See the [email_example.html](email_example.html) file for an example of the email.

### Limitations
Multi-agents jobs are not supported.  
If the instruction is external, the LLM will not be able to analyze it.

# License
This project is licensed under the Apache 2.0 License - see the [LICENSE](license) file for details


# Code of Conduct
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-v2.1%20adopted-ff69b4.svg)](code-of-conduct.md)  
Absyss SAS has adopted the [Contributor Covenant](CODE_OF_CONDUCT.md) as its Code of Conduct, and we expect project participants to adhere to it. Please read the [full text](CODE_OF_CONDUCT.md) so that you can understand what actions will and will not be tolerated.
