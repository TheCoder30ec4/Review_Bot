from typing import Literal
from pydantic import BaseModel, Field


class ReviewState(BaseModel):
    """State for code review of individual files."""
    File: str = Field(
        description="The file path being reviewed. This should be a relative file path from the repository root (e.g., 'Backend/app/main.py' or 'Frontend/src/App.tsx').",
        examples=["Backend/app/main.py", "Frontend/src/components/Button.tsx", "src/utils/helper.py"]
    )
    CriticalityStatus: Literal["OK", "Medium", "Critical"] = Field(
        description="The criticality or impact level of the review findings. Must be one of: 'OK' (minor suggestions), 'Medium' (moderate issues), or 'Critical' (severe issues requiring immediate attention).",
        examples=["OK", "Medium", "Critical"]
    )
    WhatNeedsToBeImproved: str = Field(
        description="A detailed explanation of what needs to be improved in the code. This should describe the issue, why it's a problem, and what should be changed. Be specific and actionable.",
        examples=[
            "This function lacks error handling. Add try-except blocks to handle potential exceptions.",
            "Hardcoded API endpoint should be moved to configuration file for better maintainability.",
            "Missing input validation could lead to security vulnerabilities. Add validation checks for all user inputs."
        ]
    )
    DiffCode: str = Field(
        description="The EXACT code snippet from the diff that needs to be changed. This must be extracted directly from the diff content, preserving all indentation, line breaks, and formatting. Remove diff markers (+/-) and line numbers - extract only the actual code. The code must be syntactically correct and properly formatted as it would appear in the source file. Include enough context (function signature, class definition, etc.) to make the issue clear.",
        examples=[
            "@router.get(\"/analytics/user-activity\")\nasync def get_user_activity_analytics(\n    ctx=Depends(get_admin_user),\n    db: Session = Depends(get_db)\n):\n    \"\"\"Get user activity analytics (admin only)\"\"\"\n    analytics_service = AnalyticsService(db)\n    return analytics_service.get_user_activity_analytics()",
            "def process_data(data):\n    result = data.process()\n    return result",
            "API_URL = 'https://api.example.com'"
        ]
    )
    CurrentCode: str = Field(
        description="The current/old code that needs to be changed. Extract this from the file content showing what exists now. This should be the problematic code that needs improvement. Include enough context (like function signature) to identify the exact location.",
        examples=[
            "def process_data(data):\n    result = data.process()\n    return result",
            "password = request.json['password']\nquery = f\"SELECT * FROM users WHERE password='{password}'\"",
            "API_URL = 'https://api.example.com'"
        ],
        default=""
    )
    SuggestedCode: str = Field(
        description="The improved/fixed version of the code. This should be the complete, production-ready code that solves the identified issue. Must be syntactically correct, properly formatted, and directly committable. Include the same context as CurrentCode so they can be compared.",
        examples=[
            "def process_data(data):\n    try:\n        result = data.process()\n        return result\n    except Exception as e:\n        logger.error(f\"Error processing data: {e}\")\n        raise ProcessingError(\"Failed to process data\") from e",
            "password = request.json['password']\nquery = \"SELECT * FROM users WHERE password=?\"\nresult = db.execute(query, [password])",
            "API_URL = os.getenv('API_URL', 'https://api.example.com')"
        ],
        default=""
    )
    PromptForAI: str = Field(
        description="A prompt or instruction for the AI/LLM to generate a detailed review comment. This should guide the AI on how to format and structure the review comment, including what information to include.",
        examples=[
            "Generate a code review comment explaining the security issue with this code snippet and suggest improvements.",
            "Create a review comment highlighting the missing error handling and provide recommendations.",
            "Write a detailed review comment about code quality issues in this snippet."
        ]
    )