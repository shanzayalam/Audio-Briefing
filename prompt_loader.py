"""
Prompt Loader Utility

Centralized prompt management for AI-powered modules.
Loads prompts from the prompts/ folder as Python modules.
"""

import importlib
from typing import Dict, Any


class PromptLoader:
    """Load and manage AI prompts from Python modules"""
    
    def __init__(self, prompts_package: str = "prompts"):
        """
        Initialize prompt loader
        
        Args:
            prompts_package: Package name containing prompt modules
        """
        self.prompts_package = prompts_package
        self._cache = {}
    
    def _load_module(self, module_name: str):
        """Load a prompt module"""
        if module_name in self._cache:
            return self._cache[module_name]
        
        try:
            module = importlib.import_module(f"{self.prompts_package}.{module_name}")
            self._cache[module_name] = module
            return module
        except ImportError as e:
            raise ImportError(f"Prompt module not found: {self.prompts_package}.{module_name}") from e
    
    def get_system_prompt(self, module: str) -> str:
        """
        Get system prompt for a specific module
        
        Args:
            module: Module name (research_analyst, script_writer_intro, etc.)
            
        Returns:
            str: System prompt
        """
        prompt_module = self._load_module(module)
        return prompt_module.SYSTEM_PROMPT
    
    def get_user_prompt(self, module: str, **kwargs) -> str:
        """
        Get formatted user prompt for a specific module
        
        Args:
            module: Module name
            **kwargs: Variables to format into the prompt
            
        Returns:
            str: Formatted user prompt
        """
        prompt_module = self._load_module(module)
        return prompt_module.USER_PROMPT.format(**kwargs)
    
    def reload_prompts(self):
        """Clear cache and reload all prompt modules"""
        self._cache.clear()
        # Force reimport by clearing from sys.modules
        import sys
        modules_to_remove = [key for key in sys.modules if key.startswith(f"{self.prompts_package}.")]
        for module in modules_to_remove:
            del sys.modules[module]
    
    def list_prompts(self) -> Dict[str, Any]:
        """
        List all available prompt modules
        
        Returns:
            dict: Mapping of module names to their SYSTEM_PROMPT and USER_PROMPT
        """
        import pkgutil
        import sys
        
        prompts = {}
        
        try:
            package = importlib.import_module(self.prompts_package)
            for _, name, _ in pkgutil.iter_modules(package.__path__):
                module = self._load_module(name)
                prompts[name] = {
                    "system": getattr(module, "SYSTEM_PROMPT", None),
                    "user": getattr(module, "USER_PROMPT", None)
                }
        except ImportError:
            pass
        
        return prompts


# Global prompt loader instance
prompt_loader = PromptLoader()
