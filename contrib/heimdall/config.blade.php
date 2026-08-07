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
        <small>Use <strong>CASHPILOT_READONLY_API_KEY</strong> &mdash; it is scoped to reporting endpoints and cannot deploy, stop or remove anything. Sent as a Bearer token. The admin or fleet key also works, but both grant far more than this tile needs.</small>
    </div>
</div>
