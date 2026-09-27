"""``python -m ratica`` opens the desktop app; with arguments it runs the command line."""
import sys

if len(sys.argv) > 1:
    from .cli import main

    sys.exit(main())
else:
    from .gui import main

    main()
