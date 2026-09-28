"""Where the client lives, which files are stock, and how to get a stock copy safely.

Every tool reads stock packages through `stock_bytes`, which only returns a file whose SHA-256 is the stock one. It
takes the file from `backup/client/<name>.orig` when that exists, otherwise from the client folder, and makes the
backup on first use.
"""
import hashlib
import os
import shutil

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(TOOLS, "..", ".."))
SYSTEM = os.path.join(ROOT, "Client", "Interlude", "system")
BACKUP = os.path.join(ROOT, "backup", "client")

# SHA-256 of every stock client package, taken 2026-09-28. interface.u from backup/client/interface.u.orig.
STOCK_SHA256 = {
    "Core.u": "de5f0ee0a773327bce13c96622fd3c654cff7db88b9be065d1232590c140fda0",
    "Editor.u": "da5c6fe8b2d3639286c0407695465ddfce72c2d5bbacb7c2ee0885451f0dc70f",
    "Engine.u": "9b04ff5cb4258e84dfa8efbdd85d9121f3bdcb5822a9a21ca69d200d05a69761",
    "Fire.u": "6933afddb8830aafa754a59b97782fe66dda102c58395b3776e4672aeef76527",
    "GamePlay.u": "714639cdad265a7caeaf0f91ce76bb50492390eaa3faea15ed5a28a3e830b64a",
    "IpDrv.u": "0a156f4800c5c4c9b3b12e9944a779d9c4fcd517aa25d64964fa523836191f9b",
    "LineageCreature.u": "6b13fe4e9d92e212aaac6d80bbb56370bdb43ea2be7df7aa7cafb74cfc085907",
    "LineageDeco.u": "77a3f23688df5bd8919952c5b15a59e7cc6c5507357ccaf4e443150f882bc387",
    "LineageMonster.u": "f06ac53f7df24bd13d6e7a0d25d9e3ca4e4502af2437518e49d96a053987d7b6",
    "LineageMonster2.u": "c623818bfe1b6ef201785afd4bdac3ffc20e443b4c122a78cea79c473fe99420",
    "LineageMonster3.u": "f3b211e69a4cb94aa8962d5fdd3969dad895aa214e5cf60577ec7d3f69fc5709",
    "LineageVehicle.u": "79282682d4e49df5287ecfa2d6ac89df4abb01ff6495b46f1ed16c9eaa624066",
    "LineageWarrior.u": "747b1e7c3045c748c08b03b54893dc2d29cf7103379f19804ccbeb7764224558",
    "UWindow.u": "eac8be32d9039d415989e93d8af549dc0bffe1d811e3cf46268318708e8fd3d4",
    "interface.u": "4ca40e2936138d9551412767c695b6e54e8f2843daf437536811705704b91019",
    "lineageeffect.u": "ea090154c4b8eb2f4fafab331c85fd8f7e42869ec71eb4f11323b546b550114a",
    "lineageenv.u": "0813e3a46aa3eb19c733b4212c7523a15cb4d2507b9f923bb95661a12647297c",
    "lineagenpc.u": "22208e416e5b986042fb5d67bca3a519329d81b289843b5ea442d73b2495f7d0",
    "lineagenpc2.u": "3a68b645d1912b7a882bca3bfd41f12be45286dd118798ea63244173fcb7b3fc",
    "lineagenpcev.u": "9fdf8e870e7477d6b67b1a05a401f04a76deeeabba7dca8d9a48bc01062e09fb",
    "nwindow.u": "6f3171147d83e447f2427e249c2ad73428e2b385d1557b86c53effa1062ea791",
    "udebugmenu.u": "80ce780ae87300cded6af855e83b071fbb423ace22902b12490e1bc9e10cc543",
}


class NotStock(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def client_path(name):
    return os.path.join(SYSTEM, name)


def backup_path(name):
    return os.path.join(BACKUP, name + ".orig")


def stock_bytes(name):
    """The stock file's bytes, verified by hash. Creates the backup the first time the client copy is stock."""
    want = STOCK_SHA256.get(name)
    if want is None:
        raise NotStock("%s has no recorded stock hash" % name)
    bp = backup_path(name)
    if os.path.exists(bp):
        data = open(bp, "rb").read()
        if sha256(data) != want:
            raise NotStock("backup %s is not the stock file" % bp)
        return data
    data = open(client_path(name), "rb").read()
    if sha256(data) != want:
        raise NotStock("%s is modified and there is no stock backup at %s" % (client_path(name), bp))
    os.makedirs(BACKUP, exist_ok=True)
    shutil.copy2(client_path(name), bp)
    return data


def stock_names():
    return sorted(STOCK_SHA256)
