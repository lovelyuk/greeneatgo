-- Rename the old pilot merchant label that can still appear in the customer app.
update merchants
set name = '돈토'
where qr_token = 'QR-PILOT-KIMCHI';
