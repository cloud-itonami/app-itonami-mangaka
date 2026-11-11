(import os)
(import subprocess)
(import sys)

(setv ROOT (or (os.environ.get "COM_JUNKAWASAKI_ROOT") (os.path.expanduser "~/github/com-junkawasaki")))
(setv SHIM (os.path.join ROOT "scripts" "hermes-bots-aozora" "aozora_publish.hy"))
(setv result (subprocess.run [sys.executable "-m" "hy" SHIM "mangaka" #* (cut sys.argv 1)] :timeout 900))
(sys.exit result.returncode)
