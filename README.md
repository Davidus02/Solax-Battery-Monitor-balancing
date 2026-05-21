# Solax-Battery-Monitor

Solax T58 Battery Monitor — passive RS-485 sniffer → MQTT bridge

Příprava:

   Celý projekt je třeba umístit do složky addons která se nachází v nejvyšším adresáři, nejsnadnější přístup k této složce je přes Samba server. 
   Jako další je třeba rozjet si svého MQTT Brokera + MQTT klienta v rámci Home Assistentu


   Zpřístupnění složek přes Samba: V Obchodě s doplňky najdi a nainstaluj Samba share. Před spuštěním přejdi na kartu Konfigurace u tohoto doplňku. Zadej si své údaje a        připoj Home Assistenta do Windows průzkumníku 


1.Instalace a nastavení MQTT Brokera:Zajišťuje komunikaci mezi addonem a Home Assistantem.Přejdi do Nastavení -> Doplňky -> Obchod s doplňky (Add-on store).Vyhledej a nainstaluj doplněk Mosquitto broker.Po instalaci zaškrtni Spustit při startu (Start on boot) a Hlídací pes (Watchdog) a doplněk spusť.Přejdi do Nastavení -> Zařízení a služby -> Přidat integraci.Vyhledej MQTT a přidej ji. Home Assistant by měl Mosquitto brokera automaticky detekovat. Potvrď připojení (případně zadej přihlašovací údaje do HA, pokud jsou vyžadovány).


2.Zpřístupnění složek přes Samba Share:Příprava pro přenos souborů z Windows.V Obchodě s doplňky najdi a nainstaluj Samba share.Před spuštěním přejdi na kartu Konfigurace u tohoto doplňku.Nastav si vlastní username (uživatelské jméno) a password (heslo) a konfiguraci ulož.Spusť doplněk Samba share.


3.Stažení a nahrání Solax Addonu:Stáhni si celý projekt Solax Triple Power addonu z GitHubu (jako ZIP archiv) a rozbal ho ve svém počítači.Ve Windows otevři Průzkumník souborů a do adresního řádku zadej IP adresu tvého Home Assistanta ve formátu \\192.168.x.x (nahraď reálnou IP adresou).Přihlas se údaji, které sis vytvořil v doplňku Samba share.Otevři složku addons.Zkopíruj celou rozbalenou složku projektu (tu, která obsahuje soubory jako config.json nebo config.yaml, run.sh atd.) přímo do složky addons.


4.Instalace lokálního addonu v HA:V Home Assistantovi přejdi do Nastavení -> Doplňky -> Obchod s doplňky.Vpravo nahoře klikni na tři tečky a vyber Zkontrolovat aktualizace (Check for updates). Tím se znovu načte seznam složek.Sjeď úplně dolů, kde bys měl vidět novou sekci Lokální doplňky (Local add-ons).Klikni na tvůj Solax Triple Power addon a dej Nainstalovat.Přejdi na záložku Konfigurace v addonu a vyplň potřebné údaje: IP adresu/port desky a přihlašovací údaje k MQTT brokeru (IP adresa HA, port 1883, uživatel a heslo).Doplněk spusť a zkontroluj záložku Deník (Log), zda se úspěšně připojil k desce i k MQTT.


5.Zápis senzorů do YAML konfigurace:Vyčítání dat z MQTT.Pokud se senzory nevytvoří v HA samy přes MQTT autodiscovery, je potřeba je přidat ručně do souboru configuration.yaml (případně do mqtt.yaml, pokud máš konfiguraci rozdělenou).Zde je funkční úryvek, jak takový zápis vypadá. Témata (state_topic) musíš upravit podle toho, co reálně posílá tvůj addon.YAML    


mqtt:
      sensor:
        - name: "Solax Baterie SOC"
          state_topic: "solax/battery/soc"
          unit_of_measurement: "%"
          device_class: battery
          state_class: measurement      
          value_template: "{{ value }}"
          
        - name: "Solax Baterie Napětí"
          state_topic: "solax/battery/voltage"
          unit_of_measurement: "V"
          device_class: voltage
          state_class: measurement
          
        - name: "Solax Baterie Proud"
          state_topic: "solax/battery/current"
          unit_of_measurement: "A"
          device_class: current
          state_class: measurement
    ```
    Po úpravě YAML souboru nezapomeň přejít do **Vývojářské nástroje** (Developer tools) a kliknout na **Znovu načíst ručně konfigurované entity MQTT** (nebo rovnou restartovat HA).
