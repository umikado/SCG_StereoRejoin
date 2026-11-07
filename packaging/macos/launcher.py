"""Entry point for the self-contained macOS test build."""
import sys

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        from bundle_selftest import run
        raise SystemExit(run(sys.argv[2]))
    from scg_stereorejoin.gui import main
    raise SystemExit(main())
