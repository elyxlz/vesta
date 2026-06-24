"""Unit tests for the OWA/EWS backend's XML->Graph-shape normalization."""

from xml.etree import ElementTree as ET

from microsoft_cli import owa

T = "http://schemas.microsoft.com/exchange/services/2006/types"


def _msg_xml():
    return ET.fromstring(
        f"""<t:Message xmlns:t="{T}">
          <t:ItemId Id="AAA=" ChangeKey="CK1"/>
          <t:Subject>Hello world</t:Subject>
          <t:DateTimeReceived>2026-06-04T09:57:47Z</t:DateTimeReceived>
          <t:HasAttachments>true</t:HasAttachments>
          <t:IsRead>false</t:IsRead>
          <t:Body BodyType="Text">the body</t:Body>
          <t:From><t:Mailbox><t:Name>Open Router</t:Name><t:EmailAddress>welcome@openrouter.ai</t:EmailAddress></t:Mailbox></t:From>
          <t:ToRecipients>
            <t:Mailbox><t:Name>Test User</t:Name><t:EmailAddress>user@example.com</t:EmailAddress></t:Mailbox>
          </t:ToRecipients>
          <t:Categories><t:String>Finance</t:String><t:String>Tax</t:String></t:Categories>
        </t:Message>"""
    )


def test_norm_message_maps_to_graph_shape():
    m = owa.norm_message(_msg_xml())
    assert m["id"] == "AAA="
    assert m["changeKey"] == "CK1"
    assert m["subject"] == "Hello world"
    assert m["receivedDateTime"] == "2026-06-04T09:57:47Z"
    assert m["hasAttachments"] is True
    assert m["isRead"] is False
    assert m["from"]["emailAddress"]["address"] == "welcome@openrouter.ai"
    assert m["from"]["emailAddress"]["name"] == "Open Router"
    assert m["toRecipients"][0]["emailAddress"]["address"] == "user@example.com"
    assert m["body"]["content"] == "the body"
    assert m["categories"] == ["Finance", "Tax"]


def test_norm_event_maps_to_graph_shape():
    ev = ET.fromstring(
        f"""<t:CalendarItem xmlns:t="{T}">
          <t:ItemId Id="EVT=" ChangeKey="CK2"/>
          <t:Subject>Standup</t:Subject>
          <t:Start>2026-06-10T10:00:00Z</t:Start>
          <t:End>2026-06-10T10:30:00Z</t:End>
          <t:Location>Room 1</t:Location>
          <t:IsAllDayEvent>false</t:IsAllDayEvent>
          <t:Organizer><t:Mailbox><t:EmailAddress>user@example.com</t:EmailAddress></t:Mailbox></t:Organizer>
          <t:RequiredAttendees>
            <t:Attendee><t:Mailbox><t:EmailAddress>bob@example.com</t:EmailAddress></t:Mailbox></t:Attendee>
          </t:RequiredAttendees>
        </t:CalendarItem>"""
    )
    e = owa.norm_event(ev)
    assert e["id"] == "EVT="
    assert e["subject"] == "Standup"
    assert e["start"]["dateTime"] == "2026-06-10T10:00:00Z"
    assert e["end"]["dateTime"] == "2026-06-10T10:30:00Z"
    assert e["location"]["displayName"] == "Room 1"
    assert e["organizer"]["emailAddress"]["address"] == "user@example.com"
    assert e["attendees"][0]["emailAddress"]["address"] == "bob@example.com"


def test_response_messages_raises_on_error_class():
    body = ET.fromstring(
        """<Body xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">
          <m:CreateItemResponseMessage ResponseClass="Error">
            <m:ResponseCode>ErrorAccessDenied</m:ResponseCode>
            <m:MessageText>Access is denied.</m:MessageText>
          </m:CreateItemResponseMessage>
        </Body>"""
    )
    try:
        owa._check_response_messages(body)
        assert False, "expected OwaError"
    except owa.OwaError as e:
        assert "Access is denied" in str(e)


def test_folder_mapping_aliases():
    assert 'Id="sentitems"' in owa._distinguished("sent")
    assert 'Id="deleteditems"' in owa._distinguished("deleted")
    assert 'Id="junkemail"' in owa._distinguished("junk")
