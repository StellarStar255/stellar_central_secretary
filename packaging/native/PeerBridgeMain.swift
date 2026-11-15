import Foundation
@main struct PeerBridgeMain {
    static func main() throws {
        let args=CommandLine.arguments
        guard args.count==3,args[1].count==32,args[1].allSatisfy({$0.isHexDigit}),let port=UInt16(args[2]),port>0 else {exit(2)}
        let parent=getppid()
        let monitor=Timer.scheduledTimer(withTimeInterval:2,repeats:true) { _ in
            if getppid() != parent { exit(0) }
        }
        let wifi=try WiFiRelay(serverID:args[1],upstreamPort:port);wifi.start()
        let bluetooth=try BluetoothRelay(serverID:args[1],upstreamPort:port);bluetooth.start()
        RunLoop.main.run();withExtendedLifetime((wifi,bluetooth,monitor)) {}
    }
}
