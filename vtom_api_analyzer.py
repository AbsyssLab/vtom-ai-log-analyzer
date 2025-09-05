#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VTOM API Log Analyzer
VTOM log analyzer via API with multiple LLM providers

This script retrieves VTOM logs via API, extracts job instructions and context,
then uses an LLM to analyze errors and propose solutions.
"""

import sys
import os
import json
import argparse
import logging
import urllib3
import base64
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class MailSender(ABC):
    """Abstract class for email sending"""
    
    @abstractmethod
    def __init__(self):
        pass
    
    @abstractmethod
    def send_mail(self, to_emails: List[str], cc_emails: List[str], subject: str, 
                  body_html: str, attachments: List[Dict[str, Any]] = None) -> bool:
        pass
    
    @abstractmethod
    def create_attachment(self, file_path: str, display_name: str = None) -> Dict[str, Any]:
        pass

class AzureMailSender(MailSender):
    """Class for sending emails via Microsoft Graph API with Azure authentication"""
    
    def __init__(self):
        """Initialize the sender with Azure credentials"""
        self.client_id = os.getenv('AZURE_CLIENT_ID')
        self.client_secret = os.getenv('AZURE_CLIENT_SECRET')
        self.tenant_id = os.getenv('AZURE_TENANT_ID')
        self.from_email = os.getenv('AZURE_FROM_EMAIL')
        
        if not all([self.client_id, self.client_secret, self.tenant_id, self.from_email]):
            raise ValueError("Incomplete Azure configuration. Check AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID and AZURE_FROM_EMAIL in .env")
        
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.scope = ["https://graph.microsoft.com/.default"]
        self.graph_endpoint = "https://graph.microsoft.com/v1.0"
        
    def get_access_token(self) -> str:
        """Get an access token via MSAL"""
        try:
            import msal
            
            # Create the confidential application
            app = msal.ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=self.authority
            )
            
            # Get the token
            result = app.acquire_token_for_client(scopes=self.scope)
            
            if "access_token" in result:
                logger.info("Azure access token obtained successfully")
                return result["access_token"]
            else:
                error_msg = f"Azure authentication error: {result.get('error_description', 'Unknown error')}"
                logger.error(error_msg)
                raise Exception(error_msg)
                
        except ImportError:
            raise Exception("Package 'msal' not installed. Run: pip install msal")
        except Exception as e:
            raise Exception(f"Error getting Azure token: {e}")
    
    def send_mail(self, to_emails: List[str], cc_emails: List[str], subject: str, 
                  body_html: str, attachments: List[Dict[str, Any]] = None) -> bool:
        """Send an email via Microsoft Graph API"""
        try:
            import requests
            
            # Get the access token
            access_token = self.get_access_token()
            
            # Prepare recipients
            to_recipients = [{"emailAddress": {"address": email.strip()}} for email in to_emails]
            cc_recipients = [{"emailAddress": {"address": email.strip()}} for email in cc_emails] if cc_emails else []
            
            # Prepare the message
            message = {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": body_html
                },
                "toRecipients": to_recipients,
                "ccRecipients": cc_recipients
            }
            
            # Add attachments if present
            if attachments:
                message["attachments"] = attachments
            
            # Send the email
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            url = f"{self.graph_endpoint}/users/{self.from_email}/sendMail"
            payload = {
                "message": message,
                "saveToSentItems": True
            }
            
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 202:
                logger.info(f"Email sent successfully via Azure Graph to {len(to_emails)} recipient(s)")
                return True
            else:
                error_msg = f"Error sending Azure email: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return False
                
        except ImportError:
            raise Exception("Package 'requests' not installed. Run: pip install requests")
        except Exception as e:
            logger.error(f"Error sending Azure email: {e}")
            return False
    
    def create_attachment(self, file_path: str, display_name: str = None) -> Dict[str, Any]:
        """Create an attachment object for Microsoft Graph"""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Encode in base64
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            
            # Default display name
            if not display_name:
                display_name = os.path.basename(file_path)
            
            return {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": display_name,
                "contentType": "application/octet-stream",
                "contentBytes": encoded_content
            }
            
        except Exception as e:
            logger.error(f"Error creating attachment {file_path}: {e}")
            return None

class SMTPMailSender(MailSender):
    """Class for sending emails via classic SMTP"""
    
    def __init__(self):
        """Initialize the sender with SMTP configuration"""
        self.smtp_server = os.getenv('SMTP_SERVER')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_username = os.getenv('SMTP_USERNAME')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.smtp_from_email = os.getenv('SMTP_FROM_EMAIL')
        self.smtp_use_tls = os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'
        
        if not all([self.smtp_server, self.smtp_username, self.smtp_password, self.smtp_from_email]):
            raise ValueError("Incomplete SMTP configuration. Check SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM_EMAIL in .env")
    
    def send_mail(self, to_emails: List[str], cc_emails: List[str], subject: str, 
                  body_html: str, attachments: List[Dict[str, Any]] = None) -> bool:
        """Send an email via SMTP"""
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
            
            # Create the message
            msg = MIMEMultipart()
            msg['From'] = self.smtp_from_email
            msg['To'] = ', '.join(to_emails)
            if cc_emails:
                msg['Cc'] = ', '.join(cc_emails)
            msg['Subject'] = subject
            
            # Add HTML body
            msg.attach(MIMEText(body_html, 'html'))
            
            # Add attachments if present
            if attachments:
                for attachment in attachments:
                    if attachment and 'file_path' in attachment:
                        file_path = attachment['file_path']
                        display_name = attachment.get('display_name', os.path.basename(file_path))
                        
                        with open(file_path, 'rb') as f:
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(f.read())
                        
                        encoders.encode_base64(part)
                        part.add_header('Content-Disposition', 'attachment', filename=display_name)
                        msg.attach(part)
            
            # Connection and sending
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            if self.smtp_use_tls:
                server.starttls()
            
            server.login(self.smtp_username, self.smtp_password)
            
            # Send to all recipients (to + cc)
            all_recipients = to_emails + cc_emails
            server.sendmail(self.smtp_from_email, all_recipients, msg.as_string())
            server.quit()
            
            logger.info(f"Email sent successfully via SMTP to {len(to_emails)} recipient(s)")
            return True
            
        except ImportError:
            raise Exception("Email modules not available. Check your Python installation.")
        except Exception as e:
            logger.error(f"Error sending SMTP email: {e}")
            return False
    
    def create_attachment(self, file_path: str, display_name: str = None) -> Dict[str, Any]:
        """Create an attachment object for SMTP"""
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # Default display name
            if not display_name:
                display_name = os.path.basename(file_path)
            
            return {
                "file_path": file_path,
                "display_name": display_name
            }
            
        except Exception as e:
            logger.error(f"Error creating attachment {file_path}: {e}")
            return None

class MailSenderFactory:
    """Factory to create the right type of sender according to configuration"""
    
    @staticmethod
    def create_mail_sender() -> MailSender:
        """Create the right type of sender according to MAIL_PROVIDER"""
        mail_provider = os.getenv('MAIL_PROVIDER', 'azure').lower()
        
        if mail_provider == 'azure':
            logger.info("Using Azure Graph provider for email sending")
            return AzureMailSender()
        elif mail_provider == 'smtp':
            logger.info("Using classic SMTP provider for email sending")
            return SMTPMailSender()
        else:
            raise ValueError(f"Unsupported mail provider: {mail_provider}. Use 'azure' or 'smtp'")

class VTOMAPIClient:
    """Generic client for VTOM API calls"""
    
    def __init__(self):
        """Initialize the client with VTOM server configuration"""
        self.vtom_server = os.getenv('VTOM_SERVER')
        self.vtom_port = os.getenv('VTOM_PORT', '30002')
        self.vtom_api_key = os.getenv('VTOM_API_KEY')
        
        # VTOM API versions
        self.domain_api_version = os.getenv('VTOM_DOMAIN_API_VERSION', '5.0')
        self.monitoring_api_version = os.getenv('VTOM_MONITORING_API_VERSION', '2.0')
        
        if not self.vtom_server:
            raise ValueError("Incomplete VTOM configuration. Check VTOM_SERVER in .env")
        
        if not self.vtom_api_key:
            raise ValueError("Incomplete VTOM configuration. Check VTOM_API_KEY in .env")
        
        self.base_url = f"https://{self.vtom_server}:{self.vtom_port}"
    
    def call_api(self, endpoint: str, method: str = "GET", headers: Dict[str, str] = None, 
                 data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Generic call to VTOM API"""
        try:
            import requests
            
            url = f"{self.base_url}{endpoint}"
            default_headers = {
                "Content-Type": "application/json",
                "X-API-KEY": self.vtom_api_key
            }
            if headers:
                default_headers.update(headers)
            
            logger.info(f"API call {method} to: {url}")
            
            if method.upper() == "GET":
                response = requests.get(url, headers=default_headers, verify=False)
            elif method.upper() == "POST":
                response = requests.post(url, headers=default_headers, json=data, verify=False)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=default_headers, json=data, verify=False)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            if response.status_code == 200:
                logger.info(f"API call successful: {response.status_code}")
                # Try to parse as JSON, otherwise return raw text
                try:
                    data = response.json() if response.content else None
                except ValueError:
                    # If it's not JSON, return raw text
                    data = response.text if response.content else None
                return {"success": True, "data": data}
            else:
                error_msg = f"API error {response.status_code}: {response.text}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg, "status_code": response.status_code}
                
        except ImportError:
            raise Exception("Package 'requests' not installed. Run: pip install requests")
        except Exception as e:
            logger.error(f"Error during API call: {e}")
            return {"success": False, "error": str(e)}
    
    def get_logs(self, timestamp: str, environment: str, application: str, job: str, agent: str = "localhost") -> str:
        """Retrieve log content via API (stdout and stderr)"""
        try:
            logger.info(f"Retrieving logs for timestamp: {timestamp}")
            
            # Build URLs for stdout and stderr
            base_endpoint = f"/vtom/public/monitoring/{self.monitoring_api_version}/environments/{environment}/applications/{application}/jobs/{job}/logs/{agent}/{timestamp}"
            stdout_endpoint = f"{base_endpoint}/stdout"
            stderr_endpoint = f"{base_endpoint}/stderr"
            
            # Retrieve stdout logs
            stdout_response = self.call_api(stdout_endpoint)
            stdout_content = ""
            if stdout_response.get("success") and stdout_response.get("data"):
                stdout_content = stdout_response["data"]
                logger.info(f"Stdout logs retrieved: {len(stdout_content)} characters")
            else:
                logger.warning(f"Unable to retrieve stdout logs: {stdout_response.get('error')}")
                stdout_content = f"Stdout error: {stdout_response.get('error', 'Content not available')}"
            
            # Retrieve stderr logs
            stderr_response = self.call_api(stderr_endpoint)
            stderr_content = ""
            if stderr_response.get("success"):
                # API successful (code 200)
                stderr_data = stderr_response.get("data", "")
                if stderr_data:
                    stderr_content = stderr_data
                    logger.info(f"Stderr logs retrieved: {len(stderr_content)} characters")
                else:
                    stderr_content = "(No stderr logs - normal if no error)"
                    logger.info("Empty stderr logs (normal if no error)")
            else:
                # API error (code != 200)
                logger.warning(f"Unable to retrieve stderr logs: {stderr_response.get('error')}")
                stderr_content = f"Stderr error: {stderr_response.get('error', 'Content not available')}"
            
            # Combine stdout and stderr logs
            combined_logs = f"""=== LOGS STDOUT ===
{stdout_content}

=== LOGS STDERR ===
{stderr_content}"""
            
            return combined_logs
            
        except Exception as e:
            logger.error(f"Error retrieving logs {timestamp}: {e}")
            return f"Error retrieving logs: {str(e)}"
    
    def get_instruction(self, environment: str, application: str, job: str) -> str:
        """Retrieve job instruction in cascade"""
        try:
            # Try first at job level
            endpoint = f"/vtom/public/domain/{self.domain_api_version}/environments/{environment}/applications/{application}/jobs/{job}"
            response = self.call_api(endpoint)
            
            if response.get("success") and response.get("data"):
                instruction_key = response["data"].get("instruction")
                if instruction_key:
                    return self.get_instruction_content(instruction_key, environment, application, job)
            elif not response.get("success"):
                logger.warning(f"Error retrieving job info: {response.get('error')}")
            
            # Try at application level
            endpoint = f"/vtom/public/domain/{self.domain_api_version}/environments/{environment}/applications/{application}"
            response = self.call_api(endpoint)
            
            if response.get("success") and response.get("data"):
                instruction_key = response["data"].get("instruction")
                if instruction_key:
                    return self.get_instruction_content(instruction_key, environment, application)
            elif not response.get("success"):
                logger.warning(f"Error retrieving application info: {response.get('error')}")
            
            # Try at environment level
            endpoint = f"/vtom/public/domain/{self.domain_api_version}/environments/{environment}"
            response = self.call_api(endpoint)
            
            if response.get("success") and response.get("data"):
                instruction_key = response["data"].get("instruction")
                if instruction_key:
                    return self.get_instruction_content(instruction_key, environment)
            elif not response.get("success"):
                logger.warning(f"Error retrieving environment info: {response.get('error')}")
            
            return "No instruction found (all API calls failed or no instruction configured)"
        except Exception as e:
            logger.error(f"Error retrieving instructions: {e}")
            return f"Error retrieving instructions: {str(e)}"
    
    def get_instruction_content(self, instruction_key: str, environment: str = "", application: str = "", job: str = "") -> str:
        """Retrieve instruction content"""
        try:
            logger.info(f"Retrieving instruction content: {instruction_key}")
            
            endpoint = f"/vtom/public/domain/{self.domain_api_version}/instructions/{instruction_key}"
            response = self.call_api(endpoint)
            
            if response.get("success") and response.get("data"):
                instruction_data = response["data"]
                instruction_type = instruction_data.get("type", "")
                
                if instruction_type == "Internal":
                    # Internal instruction - retrieve content
                    content = instruction_data.get("content", "")
                    if content:
                        logger.info(f"Internal instruction retrieved: {len(content)} characters")
                        return content
                    else:
                        logger.warning(f"Internal instruction {instruction_key} without content")
                        return f"Internal instruction {instruction_key} empty"
                        
                elif instruction_type == "External":
                    # External instruction - cannot be retrieved
                    logger.info(f"External instruction detected: {instruction_key}")
                    content  = instruction_data.get("url", "").replace("{VT_ENVIRONMENT_NAME}", environment).replace("{VT_APPLICATION_NAME}", application).replace("{VT_JOB_NAME}", job)
                    return f"External instruction ({instruction_key}) - {content}"
                    
                else:
                    # Unknown type
                    logger.warning(f"Unknown instruction type '{instruction_type}' for {instruction_key}")
                    return f"Unknown instruction type '{instruction_type}' for {instruction_key}"
                    
            else:
                # API error
                error_msg = response.get('error', 'Unknown error')
                logger.warning(f"Unable to retrieve instruction content {instruction_key}: {error_msg}")
                return f"Error retrieving instruction {instruction_key}: {error_msg}"
                
        except Exception as e:
            logger.error(f"Error retrieving instruction content {instruction_key}: {e}")
            return f"Error retrieving instruction: {str(e)}"
    
    def get_job_context(self, environment: str, application: str, job: str) -> Dict[str, str]:
        """Retrieve job context by merging variables from 3 levels"""
        context = {}
        
        try:
            # Variables at environment level
            endpoint = f"/vtom/public/domain/{self.domain_api_version}/environments/{environment}/variables"
            response = self.call_api(endpoint)
            if response.get("success") and response.get("data"):
                context.update(response["data"])
                logger.info(f"Environment variables retrieved: {len(response['data'])} variables")
            elif not response.get("success"):
                logger.warning(f"Error retrieving environment variables: {response.get('error')}")
            
            # Variables at application level
            endpoint = f"/vtom/public/domain/{self.domain_api_version}/environments/{environment}/applications/{application}/variables"
            response = self.call_api(endpoint)
            if response.get("success") and response.get("data"):
                context.update(response["data"])
                logger.info(f"Application variables retrieved: {len(response['data'])} variables")
            elif not response.get("success"):
                logger.warning(f"Error retrieving application variables: {response.get('error')}")
            
            # Variables at job level (highest priority)
            endpoint = f"/vtom/public/domain/{self.domain_api_version}/environments/{environment}/applications/{application}/jobs/{job}/variables"
            response = self.call_api(endpoint)
            if response.get("success") and response.get("data"):
                context.update(response["data"])
                logger.info(f"Job variables retrieved: {len(response['data'])} variables")
            elif not response.get("success"):
                logger.warning(f"Error retrieving job variables: {response.get('error')}")
            
            logger.info(f"Total context: {len(context)} variables")
            return context
            
        except Exception as e:
            logger.error(f"Error retrieving job context: {e}")
            return {"error": f"Error retrieving context: {str(e)}"}


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    def __init__(self, api_key: str):
        pass
    
    @abstractmethod
    def call_llm(self, messages: List[Dict[str, str]], model: str, temperature: float = 0.3, max_tokens: int = 2000) -> str:
        pass

class GroqProvider(LLMProvider):
    """Groq LLM provider"""
    
    def __init__(self, api_key: str):
        import groq
        self.client = groq.Groq(api_key=api_key)
    
    def call_llm(self, messages: List[Dict[str, str]], model: str = "llama-3.3-70b-versatile", temperature: float = 0.3, max_tokens: int = 2000) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider"""
    
    def __init__(self, api_key: str):
        import openai
        self.client = openai.OpenAI(api_key=api_key)
    
    def call_llm(self, messages: List[Dict[str, str]], model: str = "gpt-4", temperature: float = 0.3, max_tokens: int = 2000) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

class ClaudeProvider(LLMProvider):
    """Anthropic Claude LLM provider"""
    
    def __init__(self, api_key: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
    
    def call_llm(self, messages: List[Dict[str, str]], model: str = "claude-3-sonnet-20240229", temperature: float = 0.3, max_tokens: int = 2000) -> str:
        system_message = ""
        user_message = ""
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            elif msg["role"] == "user":
                user_message = msg["content"]
        
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_message,
            messages=[{"role": "user", "content": user_message}]
        )
        return response.content[0].text

class GoogleGeminiProvider(LLMProvider):
    """Google Gemini LLM provider"""
    
    def __init__(self, api_key: str):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.client = genai
    
    def call_llm(self, messages: List[Dict[str, str]], model: str = "gemini-pro", temperature: float = 0.3, max_tokens: int = 2000) -> str:
        # Combine system and user messages for Gemini
        combined_content = ""
        for msg in messages:
            if msg["role"] == "system":
                combined_content += f"System: {msg['content']}\n\n"
            elif msg["role"] == "user":
                combined_content += f"User: {msg['content']}"
        
        # Configure generation parameters
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        
        model_instance = self.client.GenerativeModel(
            model_name=model,
            generation_config=generation_config
        )
        
        response = model_instance.generate_content(combined_content)
        return response.text

class MistralProvider(LLMProvider):
    """Mistral AI LLM provider"""
    
    def __init__(self, api_key: str):
        from mistralai.client import MistralClient
        self.client = MistralClient(api_key=api_key)
    
    def call_llm(self, messages: List[Dict[str, str]], model: str = "mistral-large-latest", temperature: float = 0.3, max_tokens: int = 2000) -> str:
        response = self.client.chat(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

class TogetherAIProvider(LLMProvider):
    """Together AI LLM provider (OpenAI compatible)"""
    
    def __init__(self, api_key: str):
        import openai
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.together.xyz/v1"
        )
    
    def call_llm(self, messages: List[Dict[str, str]], model: str = "meta-llama/Llama-2-70b-chat-hf", temperature: float = 0.3, max_tokens: int = 2000) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content

class CohereProvider(LLMProvider):
    """Cohere LLM provider"""
    
    def __init__(self, api_key: str):
        import cohere
        self.client = cohere.Client(api_key=api_key)
    
    def call_llm(self, messages: List[Dict[str, str]], model: str = "command", temperature: float = 0.3, max_tokens: int = 2000) -> str:
        # Combine messages for Cohere
        combined_text = ""
        for msg in messages:
            if msg["role"] == "system":
                combined_text += f"System: {msg['content']}\n\n"
            elif msg["role"] == "user":
                combined_text += f"User: {msg['content']}"
        
        response = self.client.generate(
            model=model,
            prompt=combined_text,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.generations[0].text

class VTOMAPIAnalyzer:
    def __init__(self, provider: str = "groq", api_key: str = None, model: str = None):
        """Initialize the VTOM API analyzer with specified LLM provider"""
        self.provider_name = provider.lower()
        
        # Configuration LLM depuis .env ou valeurs par défaut
        self.model = model or os.getenv('LLM_MODEL') or self._get_default_model()
        self.temperature = float(os.getenv('LLM_TEMPERATURE', '0.3'))
        self.max_tokens = int(os.getenv('LLM_MAX_TOKENS', '3000'))
        
        # Get API key
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = self._get_api_key()
        
        if not self.api_key:
            raise ValueError(f"{provider.upper()} API key required. Set {self._get_env_key()} in .env")
        
        # Initialize LLM provider
        try:
            self.llm_provider = self._create_provider()
        except Exception as e:
            raise ValueError(f"Error initializing {provider} provider: {e}")
        
        # Initialize VTOM API client
        self.vtom_client = VTOMAPIClient()
    
    def _get_default_model(self) -> str:
        """Get default model for the selected provider"""
        models = {
            "groq": "llama-3.3-70b-versatile",
            "openai": "gpt-4",
            "claude": "claude-3-sonnet-20240229",
            "gemini": "gemini-pro",
            "mistral": "mistral-large-latest",
            "together": "meta-llama/Llama-2-70b-chat-hf",
            "cohere": "command"
        }
        return models.get(self.provider_name, "llama-3.3-70b-versatile")
    
    def _get_api_key(self) -> str:
        """Get API key from environment variables"""
        env_keys = {
            "groq": "GROQ_API_KEY",
            "openai": "OPENAI_API_KEY", 
            "claude": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "together": "TOGETHER_API_KEY",
            "cohere": "COHERE_API_KEY"
        }
        env_key = env_keys.get(self.provider_name, "GROQ_API_KEY")
        return os.getenv(env_key)
    
    def _get_env_key(self) -> str:
        """Get environment variable key for the provider"""
        env_keys = {
            "groq": "GROQ_API_KEY",
            "openai": "OPENAI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "together": "TOGETHER_API_KEY",
            "cohere": "COHERE_API_KEY"
        }
        return env_keys.get(self.provider_name, "GROQ_API_KEY")
    
    def _create_provider(self) -> LLMProvider:
        """Create LLM provider instance"""
        providers = {
            "groq": GroqProvider,
            "openai": OpenAIProvider,
            "claude": ClaudeProvider,
            "gemini": GoogleGeminiProvider,
            "mistral": MistralProvider,
            "together": TogetherAIProvider,
            "cohere": CohereProvider
        }
        
        provider_class = providers.get(self.provider_name)
        if not provider_class:
            raise ValueError(f"Unsupported provider: {self.provider_name}")
        
        return provider_class(self.api_key)
    
    def extract_timestamp_from_filename(self, filename: str) -> str:
        """Extract timestamp from VTOM filename"""
        # Pattern: /logs/vtom/TEST_ALM_GEO_EU_DEN_250903-110000.e
        # Look for timestamp before extension
        match = re.search(r'(\d{6}-\d{6})\.\w+$', filename)
        if match:
            return match.group(1)
        else:
            raise ValueError(f"Unable to extract timestamp from filename: {filename}")

    def create_analysis_prompt(self, logs_content: str, instruction_content: str, job_context: Dict[str, str], language: str = 'en') -> str:
        """Create the analysis prompt for VTOM logs with context"""
        context_str = "\n".join([f"  • {key}: {value}" for key, value in job_context.items()])
        
        if language == 'fr':
            prompt = f"""You are an expert in VTOM (Visual TOM) log analysis and IT problem resolution.

Analyze the following information and provide a detailed error analysis:

## LOG CONTENT:
{logs_content}

## JOB INSTRUCTION:
{instruction_content}

## JOB CONTEXT (Variables):
{context_str}

## ANALYSIS TASK:

1. **PROBLEM IDENTIFICATION**: Clearly describe the main error
2. **TECHNICAL ANALYSIS**: Explain the technical causes of the error
3. **EXECUTION CONTEXT**: Summarize the VTOM job context (name, application, environment)
4. **RECOMMENDED SOLUTIONS**: Propose concrete and prioritized solutions
5. **IMMEDIATE ACTIONS**: List the priority checks to perform
6. **PREVENTION**: Suggest measures to avoid this type of error

## RESPONSE FORMAT:
Provide your response in structured JSON format with the following fields:

{{
    "error_analysis": {{
        "main_error": "Description of the main error",
        "error_type": "Error type (e.g., network, configuration, etc.)",
        "technical_causes": ["Cause 1", "Cause 2"],
        "severity": "CRITICAL|HIGH|MEDIUM|LOW"
    }},
    "vtom_context": {{
        "job_name": "Job name",
        "application": "Application name",
        "environment": "Environment",
        "execution_date": "Execution date"
    }},
    "solutions": {{
        "immediate_actions": ["Action 1", "Action 2"],
        "short_term": ["Solution 1", "Solution 2"],
        "long_term": ["Measure 1", "Measure 2"]
    }},
    "technical_details": {{
        "affected_components": ["Component 1", "Component 2"],
        "error_codes": ["Code 1", "Code 2"],
        "network_issues": "Description of network issues if applicable"
    }},
    "recommendations": {{
        "priority_1": "Priority recommendation 1",
        "priority_2": "Priority recommendation 2",
        "priority_3": "Priority recommendation 3"
    }}
}}

Be precise, technical and practical in your recommendations."""
        else:  # English
            prompt = f"""You are an expert in VTOM (Visual TOM) log analysis and IT problem resolution.

Analyze the following information and provide a detailed error analysis:

## LOG CONTENT:
{logs_content}

## JOB INSTRUCTION:
{instruction_content}

## JOB CONTEXT (Variables):
{context_str}

## ANALYSIS TASK:

1. **PROBLEM IDENTIFICATION**: Clearly describe the main error
2. **TECHNICAL ANALYSIS**: Explain the technical causes of the error
3. **EXECUTION CONTEXT**: Summarize the VTOM job context (name, application, environment)
4. **RECOMMENDED SOLUTIONS**: Propose concrete and prioritized solutions
5. **IMMEDIATE ACTIONS**: List the priority checks to perform
6. **PREVENTION**: Suggest measures to avoid this type of error

## RESPONSE FORMAT:
Provide your response in structured JSON format with the following fields:

{{
    "error_analysis": {{
        "main_error": "Description of the main error",
        "error_type": "Error type (e.g., network, configuration, etc.)",
        "technical_causes": ["Cause 1", "Cause 2"],
        "severity": "CRITICAL|HIGH|MEDIUM|LOW"
    }},
    "vtom_context": {{
        "job_name": "Job name",
        "application": "Application name",
        "environment": "Environment",
        "execution_date": "Execution date"
    }},
    "solutions": {{
        "immediate_actions": ["Action 1", "Action 2"],
        "short_term": ["Solution 1", "Solution 2"],
        "long_term": ["Measure 1", "Measure 2"]
    }},
    "technical_details": {{
        "affected_components": ["Component 1", "Component 2"],
        "error_codes": ["Code 1", "Code 2"],
        "network_issues": "Description of network issues if applicable"
    }},
    "recommendations": {{
        "priority_1": "Priority recommendation 1",
        "priority_2": "Priority recommendation 2",
        "priority_3": "Priority recommendation 3"
    }}
}}

Be precise, technical and practical in your recommendations."""
        
        return prompt

    def analyze_logs_with_llm(self, logs_content: str, instruction_content: str, job_context: Dict[str, str], language: str = 'en') -> Dict[str, Any]:
        """Analyze VTOM logs with context using LLM"""
        
        # Create the analysis prompt
        prompt = self.create_analysis_prompt(logs_content, instruction_content, job_context, language)
        
        try:
            logger.info("Calling LLM for log analysis...")
            system_message = "You are an expert in VTOM log analysis and IT problem resolution. Always respond in English and in the requested JSON format." if language == 'en' else "You are an expert in VTOM log analysis and IT problem resolution. Always respond in French and in the requested JSON format."
            
            response = self.llm_provider.call_llm(
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            logger.info("LLM analysis completed")
            
            # Try to parse the JSON response
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                # If JSON is not valid, try to extract the JSON part
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                else:
                    logger.warning("Could not parse LLM JSON response, returning raw response")
                    return {
                        "error": "Invalid JSON response",
                        "raw_response": response
                    }
                    
        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            return {
                "error": f"LLM call failed: {str(e)}",
                "raw_response": ""
            }

    def send_analysis_email(self, to_emails: List[str], cc_emails: List[str], 
                           logs_content: str, instruction_content: str, job_context: Dict[str, str],
                           analysis: Dict[str, Any], language: str = 'en') -> bool:
        """Send analysis by email with data retrieved via API"""
        try:
            # Initialize sender via factory
            mail_sender = MailSenderFactory.create_mail_sender()
            
            # Create email subject
            vtom_context = analysis.get('vtom_context', {})
            job_name = vtom_context.get('job_name', 'Unknown')
            error_analysis = analysis.get('error_analysis', {})
            severity = error_analysis.get('severity', 'Unknown')
            
            if language == 'fr':
                subject = f"Analyse VTOM - {job_name} - {severity}"
            else:
                subject = f"VTOM Analysis - {job_name} - {severity}"
            
            # Prepare content for email body
            summary_content = self.create_summary_text(analysis, language)
            context_content = "\n".join([f"{key}: {value}" for key, value in job_context.items()])
            
            # Create HTML email body with content included (except logs)
            body_html = self.create_email_body(analysis, language, {
                'summary': summary_content,
                'instruction': instruction_content,
                'context': context_content
            })
            
            # Prepare attachments - only logs as attachment
            attachments = []
            
            # Create temporary file for logs attachment
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
                f.write(logs_content)
                logs_file = f.name
            
            logs_attachment = mail_sender.create_attachment(logs_file, "vtom_logs.txt")
            if logs_attachment:
                attachments.append(logs_attachment)
            
            # Send the email
            success = mail_sender.send_mail(to_emails, cc_emails, subject, body_html, attachments)
            
            # Clean up temporary files
            try:
                os.unlink(logs_file)
            except:
                pass
            
            if success:
                logger.info(f"Analysis email sent successfully to {len(to_emails)} recipient(s)")
            else:
                logger.error("Failed to send analysis email")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending analysis email: {e}")
            return False

    def create_email_body(self, analysis: Dict[str, Any], language: str = 'en', additional_content: Dict[str, str] = None) -> str:
        """Create the HTML email body"""
        if analysis.get("error"):
            if language == 'fr':
                return f"""
                <html>
                <body>
                    <h2>Erreur d'analyse VTOM</h2>
                    <p>Une erreur s'est produite lors de l'analyse des logs VTOM.</p>
                    <pre>{analysis.get('raw_response', 'Aucune réponse')}</pre>
                </body>
                </html>
                """
            else:
                return f"""
                <html>
                <body>
                    <h2>VTOM Analysis Error</h2>
                    <p>An error occurred during VTOM log analysis.</p>
                    <pre>{analysis.get('raw_response', 'No response')}</pre>
                </body>
                </html>
                """
        
        error_analysis = analysis.get('error_analysis', {})
        vtom_context = analysis.get('vtom_context', {})
        solutions = analysis.get('solutions', {})
        
        if language == 'fr':
            # Create HTML in French
            html = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    .header {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; }}
                    .error {{ background-color: #ffe6e6; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .solution {{ background-color: #e6f3ff; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .section {{ margin: 15px 0; }}
                    .section h3 {{ color: #333; border-bottom: 2px solid #ddd; padding-bottom: 5px; }}
                    ul {{ margin: 5px 0; }}
                    li {{ margin: 5px 0; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📊 Analyse des Logs VTOM</h1>
                    <p><strong>Date d'analyse :</strong> {datetime.now().strftime('%d/%m/%Y à %H:%M')}</p>
                </div>
                
                <div class="section">
                    <h3>📋 Contexte VTOM</h3>
                    <ul>
                        <li><strong>Job :</strong> {vtom_context.get('job_name', 'N/A')}</li>
                        <li><strong>Application :</strong> {vtom_context.get('application', 'N/A')}</li>
                        <li><strong>Environnement :</strong> {vtom_context.get('environment', 'N/A')}</li>
                        <li><strong>Date d'exécution :</strong> {vtom_context.get('execution_date', 'N/A')}</li>
                    </ul>
                </div>
                
                <div class="error">
                    <h3>🚨 Analyse de l'Erreur</h3>
                    <ul>
                        <li><strong>Erreur principale :</strong> {error_analysis.get('main_error', 'N/A')}</li>
                        <li><strong>Type d'erreur :</strong> {error_analysis.get('error_type', 'N/A')}</li>
                        <li><strong>Sévérité :</strong> {error_analysis.get('severity', 'N/A')}</li>
                    </ul>
                </div>
            """
        else:
            # Create HTML in English
            html = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    .header {{ background-color: #f0f0f0; padding: 15px; border-radius: 5px; }}
                    .error {{ background-color: #ffe6e6; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .solution {{ background-color: #e6f3ff; padding: 15px; border-radius: 5px; margin: 10px 0; }}
                    .section {{ margin: 15px 0; }}
                    .section h3 {{ color: #333; border-bottom: 2px solid #ddd; padding-bottom: 5px; }}
                    ul {{ margin: 5px 0; }}
                    li {{ margin: 5px 0; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📊 VTOM Log Analysis</h1>
                    <p><strong>Analysis Date:</strong> {datetime.now().strftime('%d/%m/%Y at %H:%M')}</p>
                </div>
                
                <div class="section">
                    <h3>📋 VTOM Context</h3>
                    <ul>
                        <li><strong>Job:</strong> {vtom_context.get('job_name', 'N/A')}</li>
                        <li><strong>Application:</strong> {vtom_context.get('application', 'N/A')}</li>
                        <li><strong>Environment:</strong> {vtom_context.get('environment', 'N/A')}</li>
                        <li><strong>Execution Date:</strong> {vtom_context.get('execution_date', 'N/A')}</li>
                    </ul>
                </div>
                
                <div class="error">
                    <h3>🚨 Error Analysis</h3>
                    <ul>
                        <li><strong>Main Error:</strong> {error_analysis.get('main_error', 'N/A')}</li>
                        <li><strong>Error Type:</strong> {error_analysis.get('error_type', 'N/A')}</li>
                        <li><strong>Severity:</strong> {error_analysis.get('severity', 'N/A')}</li>
                    </ul>
                </div>
            """
        
        # Add technical causes
        technical_causes = error_analysis.get('technical_causes', [])
        if technical_causes:
            if language == 'fr':
                html += f"""
                <div class="section">
                    <h3>🔍 Causes Techniques</h3>
                    <ul>
                """
            else:
                html += f"""
                <div class="section">
                    <h3>🔍 Technical Causes</h3>
                    <ul>
                """
            for cause in technical_causes:
                html += f"<li>{cause}</li>"
            html += "</ul></div>"
        
        # Add immediate actions
        immediate_actions = solutions.get('immediate_actions', [])
        if immediate_actions:
            if language == 'fr':
                html += f"""
                <div class="solution">
                    <h3>⚡ Actions Immédiates</h3>
                    <ul>
                """
            else:
                html += f"""
                <div class="solution">
                    <h3>⚡ Immediate Actions</h3>
                    <ul>
                """
            for action in immediate_actions:
                html += f"<li>{action}</li>"
            html += "</ul></div>"
        
        # Add short-term solutions
        short_term = solutions.get('short_term', [])
        if short_term:
            if language == 'fr':
                html += f"""
                <div class="section">
                    <h3>📋 Solutions à Court Terme</h3>
                    <ul>
                """
            else:
                html += f"""
                <div class="section">
                    <h3>📋 Short-term Solutions</h3>
                    <ul>
                """
            for solution in short_term:
                html += f"<li>{solution}</li>"
            html += "</ul></div>"
        
        # Add recommendations
        recommendations = analysis.get('recommendations', {})
        if recommendations:
            if language == 'fr':
                html += f"""
                <div class="section">
                    <h3>🎯 Recommandations Prioritaires</h3>
                    <ul>
                """
            else:
                html += f"""
                <div class="section">
                    <h3>🎯 Priority Recommendations</h3>
                    <ul>
                """
            for priority, rec in recommendations.items():
                priority_name = priority.replace('_', ' ').title()
                html += f"<li><strong>{priority_name}:</strong> {rec}</li>"
            html += "</ul></div>"
        
        # Add technical details
        technical_details = analysis.get('technical_details', {})
        if technical_details:
            if language == 'fr':
                html += f"""
                <div class="section">
                    <h3>🔧 Détails Techniques</h3>
                    <ul>
                """
            else:
                html += f"""
                <div class="section">
                    <h3>🔧 Technical Details</h3>
                    <ul>
                """
            for key, value in technical_details.items():
                if isinstance(value, list):
                    html += f"<li><strong>{key.replace('_', ' ').title()}:</strong> {', '.join(value)}</li>"
                else:
                    html += f"<li><strong>{key.replace('_', ' ').title()}:</strong> {value}</li>"
            html += "</ul></div>"
        
        # Add additional content if provided
        if additional_content:
            # Add summary
            if additional_content.get('summary'):
                if language == 'fr':
                    html += f"""
                    <div class="section">
                        <h3>📄 Résumé de l'Analyse</h3>
                        <pre style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap; font-family: monospace;">{additional_content['summary']}</pre>
                    </div>
                    """
                else:
                    html += f"""
                    <div class="section">
                        <h3>📄 Analysis Summary</h3>
                        <pre style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap; font-family: monospace;">{additional_content['summary']}</pre>
                    </div>
                    """
            
            
            # Add instruction
            if additional_content.get('instruction'):
                if language == 'fr':
                    html += f"""
                    <div class="section">
                        <h3>📝 Consigne du Job</h3>
                        <pre style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap; font-family: monospace;">{additional_content['instruction']}</pre>
                    </div>
                    """
                else:
                    html += f"""
                    <div class="section">
                        <h3>📝 Job Instruction</h3>
                        <pre style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap; font-family: monospace;">{additional_content['instruction']}</pre>
                    </div>
                    """
            
            # Add context
            if additional_content.get('context'):
                if language == 'fr':
                    html += f"""
                    <div class="section">
                        <h3>🔧 Contexte (Variables)</h3>
                        <pre style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap; font-family: monospace;">{additional_content['context']}</pre>
                    </div>
                    """
                else:
                    html += f"""
                    <div class="section">
                        <h3>🔧 Context (Variables)</h3>
                        <pre style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; white-space: pre-wrap; font-family: monospace;">{additional_content['context']}</pre>
                    </div>
                    """
        
        # Add attachments section
        if language == 'fr':
            html += """
                <div class="section">
                    <h3>📎 Pièces Jointes</h3>
                    <p>Ce mail contient les fichiers suivants en pièce jointe :</p>
                    <ul>
                        <li>Fichier de logs VTOM (stdout + stderr)</li>
                    </ul>
                </div>
                
                <div style="margin-top: 30px; padding: 15px; background-color: #f9f9f9; border-radius: 5px;">
                    <p><em>Analyse générée automatiquement par l'analyseur de logs VTOM avec LLM via API</em></p>
                </div>
            </body>
            </html>
            """
        else:
            html += """
                <div class="section">
                    <h3>📎 Attachments</h3>
                    <p>This email contains the following files as attachments:</p>
                    <ul>
                        <li>VTOM logs file (stdout + stderr)</li>
                    </ul>
                </div>
                
                <div style="margin-top: 30px; padding: 15px; background-color: #f9f9f9; border-radius: 5px;">
                    <p><em>Analysis automatically generated by VTOM log analyzer with LLM via API</em></p>
                </div>
            </body>
            </html>
            """
        
        return html

    def create_summary_text(self, analysis: Dict[str, Any], language: str = 'en') -> str:
        """Create a text summary of the analysis"""
        if analysis.get("error"):
            if language == 'fr':
                return f"Erreur d'analyse: {analysis.get('error')}\n\nRéponse brute: {analysis.get('raw_response', 'Aucune réponse')}"
            else:
                return f"Analysis error: {analysis.get('error')}\n\nRaw response: {analysis.get('raw_response', 'No response')}"
        
        error_analysis = analysis.get('error_analysis', {})
        vtom_context = analysis.get('vtom_context', {})
        solutions = analysis.get('solutions', {})
        
        if language == 'fr':
            summary = f"""ANALYSE VTOM - {datetime.now().strftime('%d/%m/%Y à %H:%M')}

CONTEXTE:
- Job: {vtom_context.get('job_name', 'N/A')}
- Application: {vtom_context.get('application', 'N/A')}
- Environnement: {vtom_context.get('environment', 'N/A')}

ERREUR:
- Principale: {error_analysis.get('main_error', 'N/A')}
- Type: {error_analysis.get('error_type', 'N/A')}
- Sévérité: {error_analysis.get('severity', 'N/A')}

CAUSES TECHNIQUES:
"""
            
            for cause in error_analysis.get('technical_causes', []):
                summary += f"- {cause}\n"
            
            summary += "\nACTIONS IMMÉDIATES:\n"
            for action in solutions.get('immediate_actions', []):
                summary += f"- {action}\n"
            
            summary += "\nSOLUTIONS COURT TERME:\n"
            for solution in solutions.get('short_term', []):
                summary += f"- {solution}\n"
        else:
            summary = f"""VTOM ANALYSIS - {datetime.now().strftime('%d/%m/%Y at %H:%M')}

CONTEXT:
- Job: {vtom_context.get('job_name', 'N/A')}
- Application: {vtom_context.get('application', 'N/A')}
- Environment: {vtom_context.get('environment', 'N/A')}

ERROR:
- Main: {error_analysis.get('main_error', 'N/A')}
- Type: {error_analysis.get('error_type', 'N/A')}
- Severity: {error_analysis.get('severity', 'N/A')}

TECHNICAL CAUSES:
"""
            
            for cause in error_analysis.get('technical_causes', []):
                summary += f"- {cause}\n"
            
            summary += "\nIMMEDIATE ACTIONS:\n"
            for action in solutions.get('immediate_actions', []):
                summary += f"- {action}\n"
            
            summary += "\nSHORT-TERM SOLUTIONS:\n"
            for solution in solutions.get('short_term', []):
                summary += f"- {solution}\n"
        
        return summary

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="VTOM log analyzer via API with multiple LLM providers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage examples:
  python vtom_api_analyzer.py -f "/logs/vtom/TEST_ALM_GEO_EU_DEN_250903-110000.e" -e "MyEnvironment" -a "MyApplication" -j "MyJob" --to "admin@domain.com"
  python vtom_api_analyzer.py -f "/logs/vtom/TEST_ALM_GEO_EU_DEN_250903-110000.e" -e "MyEnvironment" -a "MyApplication" -j "MyJob" --to "admin@domain.com" --cc "tech@domain.com"
        """
    )
    
    parser.add_argument(
        '-f', '--filename',
        required=True,
        help='Full path to VTOM log file (ex: /logs/vtom/TEST_ALM_GEO_EU_DEN_250903-110000.e)'
    )
    
    parser.add_argument(
        '-e', '--environment',
        required=True,
        help='VTOM environment name'
    )
    
    parser.add_argument(
        '-a', '--application',
        required=True,
        help='VTOM application name'
    )
    
    parser.add_argument(
        '-j', '--job',
        required=True,
        help='VTOM job name'
    )
    
    parser.add_argument(
        '--agent',
        required=True,
        help='Name of the VTOM agent'
    )
    
    parser.add_argument(
        '--to',
        required=True,
        help='Email addresses of recipients (separated by commas)'
    )
    
    parser.add_argument(
        '--cc',
        help='Email addresses in copy (separated by commas)'
    )
    
    parser.add_argument(
        '--language',
        choices=['en', 'fr'],
        default='en',
        help='Language for LLM analysis and email content (en/fr)'
    )
    
    args = parser.parse_args()
    
    try:
        # Initialize analyzer
        analyzer = VTOMAPIAnalyzer()
        
        # Extract timestamp from filename
        timestamp = analyzer.extract_timestamp_from_filename(args.filename)
        print(f"Extracted timestamp: {timestamp}")
        
        # Get logs, instruction and context via API
        logs_content = analyzer.vtom_client.get_logs(timestamp, args.environment, args.application, args.job, args.agent)
        instruction_content = analyzer.vtom_client.get_instruction(args.environment, args.application, args.job)
        job_context = analyzer.vtom_client.get_job_context(args.environment, args.application, args.job)
        
        print(f"Logs: {len(logs_content)} characters")
        print(f"Instruction: {len(instruction_content)} characters")
        print(f"Context: {len(job_context)} variables")
        
        # Analyze logs with LLM
        print(f"\n🤖 Analyzing logs with LLM ({args.language.upper()})...")
        analysis_result = analyzer.analyze_logs_with_llm(logs_content, instruction_content, job_context, args.language)
        
        # Display analysis results
        if "error" in analysis_result:
            print(f"❌ Error during LLM analysis: {analysis_result['error']}")
            if analysis_result.get("raw_response"):
                print(f"Raw response: {analysis_result['raw_response'][:500]}...")
        else:
            print("\n✅ LLM analysis completed successfully!")
            
            # Display key findings
            if "error_analysis" in analysis_result:
                error_analysis = analysis_result["error_analysis"]
                print(f"\n🔍 MAIN ERROR: {error_analysis.get('main_error', 'Not identified')}")
                print(f"📊 SEVERITY: {error_analysis.get('severity', 'Not defined')}")
                print(f"🏷️  TYPE: {error_analysis.get('error_type', 'Not defined')}")
            
            # Display immediate actions
            if "solutions" in analysis_result and "immediate_actions" in analysis_result["solutions"]:
                actions = analysis_result["solutions"]["immediate_actions"]
                if actions:
                    print(f"\n🚨 IMMEDIATE ACTIONS:")
                    for i, action in enumerate(actions, 1):
                        print(f"  {i}. {action}")
        
        print(f"\n📊 Analysis completed - {len(str(analysis_result))} characters of results")
        
        # Send email notification
        print("\n📧 Sending analysis by email...")
        to_emails = [email.strip() for email in args.to.split(',')]
        cc_emails = [email.strip() for email in args.cc.split(',')] if args.cc else []
        
        email_success = analyzer.send_analysis_email(
            to_emails=to_emails,
            cc_emails=cc_emails,
            logs_content=logs_content,
            instruction_content=instruction_content,
            job_context=job_context,
            analysis=analysis_result,
            language=args.language
        )
        
        if email_success:
            print("✅ Email sent successfully!")
        else:
            print("❌ Failed to send email")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
