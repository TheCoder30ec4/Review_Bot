# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Nothing yet.

## [0.0.1] - 2025-12-11

### Added
- Initial release of Code Review Bot
- Complete LangGraph workflow implementation
- Reflexion validation system with confidence scoring
- Retry mechanism for failed reviews (up to 2 attempts)
- Security gates ensuring only approved comments are posted
- Memory management with session persistence
- Comprehensive logging system
- Custom exception hierarchy
- AI-ready prompt generation with file paths
- Before/after code visualization
- Duplicate comment prevention
- Production standards enforcement
- GitHub PR fetching and analysis
- File parsing and selection logic
- Fundamental review generation capabilities
- GitHub Actions workflow to trigger the review bot from pull requests
- GitHub Actions workflow for deploying the service to Render
- GitHub Actions workflow for CodeQL security analysis

### Changed
- Centralized prompt management in PromptLibrary
- Improved error handling throughout the system
- Enhanced logging with appropriate levels
- Modular architecture with clear separation of concerns

### Technical
- LangGraph orchestration framework
- Pydantic models for type safety
- GitHub API integration
- Comprehensive test coverage foundation

### Infrastructure
- Project structure and organization
- Dependency management with uv
- Docker support foundation
- CI/CD pipeline setup
- CI workflows for PR-triggered review, Render deployment, and CodeQL analysis

---

## Types of changes
- `Added` for new features
- `Changed` for changes in existing functionality
- `Deprecated` for soon-to-be removed features
- `Removed` for now removed features
- `Fixed` for any bug fixes
- `Security` in case of vulnerabilities

---

## Development Roadmap

### Planned for v0.2.0
- Multi-language support beyond Python
- Custom rules engine for organization-specific standards
- Batch processing for multiple PRs
- Advanced analytics dashboard
- Webhook-based triggers

### Planned for v0.3.0
- Integration APIs for external tools
- Custom model support beyond Groq
- Advanced code analysis features
- Performance optimizations
- Enterprise security enhancements

---

For more information about upcoming features, see the [Roadmap](ROADMAP.md) or join our [Discussions](https://github.com/your-org/code-review-bot/discussions).
