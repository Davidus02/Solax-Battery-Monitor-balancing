# Solax-Battery-Monitor

Solax T58 Battery Monitor — passive RS-485 sniffer → MQTT bridge

Příprava:

   Celý projekt je třeba umístit do složky addons která se nachází v nejvyšším adresáři, nejsnadnější přístup k této složce je přes Samba server. 
   Jako další je třeba rozjet si svého MQTT Brokera + MQTT klienta v rámci Home Assistentu.


   Zpřístupnění složek přes Samba: V Obchodě s doplňky najdi a nainstaluj Samba share. Před spuštěním přejdi na kartu Konfigurace u tohoto doplňku. Zadej si své údaje a        připoj Home Assistenta do Windows průzkumníku.


   Instalace a nastavení MQTT Brokera:Zajišťuje komunikaci mezi addonem a Home Assistantem. Přejdi do Nastavení -> Doplňky -> Obchod s doplňky (Add-on store).Vyhledej a        nainstaluj doplněk Mosquitto broker.Po instalaci doplněk spusť. Přejdi do Nastavení -> Zařízení a služby -> Přidat integraci. Vyhledej MQTT a přidej ji. Home Assistant      by měl Mosquitto brokera automaticky detekovat.


Stažení a nahrání Solax Addonu: Stáhni si celý projekt Solax Triple Power addonu z GitHubu (jako ZIP archiv) a rozbal ho ve svém počítači.Ve Windows otevři Průzkumník souborů a do adresního řádku zadej IP adresu tvého Home Assistanta ve formátu \\192.168.x.x. Přihlas se údaji, které sis vytvořil v doplňku Samba share. Otevři složku addons. Zkopíruj celou rozbalenou složku projektu přímo do složky addons.


Instalace lokálního addonu v HA: V Home Assistantovi přejdi do Nastavení -> Doplňky -> Obchod s doplňky. Vpravo nahoře klikni na tři tečky a vyber Zkontrolovat aktualizace (Check for updates). Tím se znovu načte seznam složek. Měl bys vidět novou sekci Lokální doplňky (Local add-ons). Klikni na Solax Triple Power addon a dej Nainstalovat. Přejdi na záložku Konfigurace v addonu a vyplň potřebné údaje: IP adresu/port desky a přihlašovací údaje k MQTT brokeru (IP adresa HA, port 1883, uživatel a heslo). Doplněk spusť a zkontroluj (Log), zda se úspěšně připojil k desce i k MQTT. 

Pro MQTT doporučuji udělat svého vlastního uživatele který má omezené práva.


Zápis senzorů do YAML konfigurace: Je potřeba je přidat ručně do souboru mqtt.yaml.
Pokud tuto složku nemáte je třeba v configuration.yaml přidat tuto část:  

      mqtt: !include mqtt.yaml 

potom stačí ve stejném hlavním adresáři udělat novou složku s názvem: mqtt.yaml


Zde příklad zápisu do složky 
Celá mqtt složka s entitami je dodaná v souborech
  
      sensor:

    # ==========================================
    # --- MODUL 1 ---
    # ==========================================
    - name: "Solax Baterie 1 - Proud"
      state_topic: "solax/t58/1/state"
      value_template: "{{ value_json.current }}"
      unit_of_measurement: "A"
      device_class: current
      state_class: measurement

Po úpravě YAML souboru je třeba jít: **Vývojářské nástroje** (Developer tools) a kliknout na **Znovu načíst ručně konfigurované entity MQTT** (nebo rovnou restartovat HA).
