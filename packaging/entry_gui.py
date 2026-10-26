import sys

if __name__ == '__main__':
    if '--capture-worker' in sys.argv:
        from secretary.capture_worker import main
    elif '--model-api-worker' in sys.argv:
        from secretary.model_api import main
    else:
        from secretary.launcher import main
    main()
