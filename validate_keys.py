"""Legacy entrypoint kept for compatibility.

Validation is now integrated into the background pipeline and runs
concurrently with search in the web service.
"""

from app.main import main


if __name__ == "__main__":
    main()
