<div class="row">
    <div class="input-group col">
        {!! Form::label('url', 'URL') !!}
        {!! Form::text('config[url]', isset($item)? $item->getconfig()->url : null, ['placeholder' => 'http://cashpilot.local:8080/']) !!}
    </div>
</div>
<div class="row">
    <div class="input-group col">
        {!! Form::label('access_token', 'API key') !!}
        {!! Form::text('config[access_token]', isset($item)? $item->getconfig()->access_token : null) !!}
        <small>Either CASHPILOT_ADMIN_API_KEY or your fleet key. Sent as a Bearer token. Note that CashPilot has no read-only token today, so whichever you use grants more than this tile needs &mdash; use it only on a dashboard you control.</small>
    </div>
</div>
